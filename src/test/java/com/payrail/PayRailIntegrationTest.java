package com.payrail;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.payrail.api.ApiException;
import com.payrail.api.PaymentController.CreateRequest;
import com.payrail.auth.ApiKeyHasher;
import com.payrail.auth.TenantContext;
import com.payrail.domain.PaymentIntent;
import com.payrail.migration.PaymentV2Service;
import com.payrail.outbox.OutboxRepository;
import com.payrail.service.CreatePaymentCommand;
import com.payrail.service.IdempotencyService;
import com.payrail.service.PaymentService;
import com.payrail.service.ProviderCompletion;
import com.payrail.service.SimulatedProvider;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers
@AutoConfigureMockMvc
@SpringBootTest(
    properties = {
      "payrail.rate-limit.enabled=false",
      "payrail.outbox.enabled=false",
      "spring.kafka.listener.auto-startup=false",
      "payrail.provider.fail-after-accept-every=1",
      "payrail.migration.shadow-read-percent=100",
      "payrail.migration.v2-read-percent=100"
    })
class PayRailIntegrationTest {
  @Container
  static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16.6-alpine");

  @DynamicPropertySource
  static void database(DynamicPropertyRegistry r) {
    r.add("spring.datasource.url", POSTGRES::getJdbcUrl);
    r.add("spring.datasource.username", POSTGRES::getUsername);
    r.add("spring.datasource.password", POSTGRES::getPassword);
  }

  @Autowired PaymentService payments;
  @Autowired IdempotencyService idempotency;
  @Autowired JdbcTemplate jdbc;
  @Autowired ObjectMapper mapper;
  @Autowired TransactionTemplate tx;
  @Autowired PaymentV2Service migration;
  @Autowired OutboxRepository outbox;
  @Autowired SimulatedProvider provider;
  @Autowired MockMvc http;
  @Autowired ApiKeyHasher apiKeyHasher;

  @BeforeEach
  void clean() {
    jdbc.execute(
        "truncate processed_events, simulated_provider_operations, outbox_events, ledger_entries, ledger_transactions, refunds, payment_intents_v2, idempotency_records, payment_intents cascade");
    jdbc.update("update migration_checkpoints set last_key=null,rows_processed=0");
    TenantContext.set("tenant_demo");
  }

  @AfterEach
  void clear() {
    TenantContext.clear();
  }

  @Test
  void concurrentDuplicateExecutesOneCreateAndReplaysPinnedResponse() throws Exception {
    var request = new CreateRequest(1000, "usd", "automatic", mapper.readTree("{\"z\":1,\"a\":2}"));
    var pool = Executors.newFixedThreadPool(8);
    List<Callable<PaymentIntent>> calls = new ArrayList<>();
    for (int i = 0; i < 8; i++)
      calls.add(
          () -> {
            TenantContext.set("tenant_demo");
            try {
              return executePayment(
                  new IdempotencyService.RawCommand(
                      "same-key",
                      "payment_intents.create",
                      "2026-01-01",
                      request,
                      201,
                      () ->
                          payments.create(
                              new CreatePaymentCommand(
                                  request.amount(),
                                  request.currency(),
                                  request.captureMethod(),
                                  request.metadata()))));
            } finally {
              TenantContext.clear();
            }
          });
    var results = pool.invokeAll(calls);
    pool.shutdown();
    assertThat(results).extracting(f -> f.get().id()).containsOnly(results.get(0).get().id());
    assertThat(jdbc.queryForObject("select count(*) from payment_intents", Long.class))
        .isEqualTo(1);
    PaymentIntent replay =
        executePayment(
            new IdempotencyService.RawCommand(
                "same-key",
                "payment_intents.create",
                "2026-01-01",
                new CreateRequest(1000, "usd", "automatic", mapper.readTree("{\"a\":2,\"z\":1}")),
                201,
                () -> {
                  throw new AssertionError("must replay");
                }));
    assertThat(replay.id()).isEqualTo(results.get(0).get().id());
  }

  @Test
  void sameKeyDifferentFingerprintConflicts() {
    var one = new CreateRequest(100, "usd", "automatic", null);
    executePayment(
        new IdempotencyService.RawCommand(
            "key", "create", "2026-01-01", one, 201, () -> create(100, "usd", "automatic")));
    assertThatThrownBy(
            () ->
                executePayment(
                    new IdempotencyService.RawCommand(
                        "key",
                        "create",
                        "2026-01-01",
                        new CreateRequest(101, "usd", "automatic", null),
                        201,
                        () -> create(101, "usd", "automatic"))))
        .isInstanceOf(ApiException.class)
        .extracting(e -> ((ApiException) e).code())
        .isEqualTo("idempotency_conflict");
  }

  @Test
  void manualCapturePostsExactlyOneBalancedImmutableJournal() {
    PaymentIntent p = create(500, "usd", "manual");
    payments.confirm(p.id());
    payments.capture(p.id(), 500);
    assertThat(jdbc.queryForObject("select sum(debit)-sum(credit) from ledger_entries", Long.class))
        .isZero();
    assertThat(jdbc.queryForObject("select count(*) from ledger_transactions", Long.class))
        .isEqualTo(1);
    assertThatThrownBy(
            () ->
                tx.executeWithoutResult(
                    s -> jdbc.update("update ledger_entries set debit=499 where debit=500")))
        .isInstanceOf(DataIntegrityViolationException.class);
  }

  @Test
  void databaseRejectsEmptyAndUnbalancedJournals() {
    PaymentIntent p = create(100, "usd", "manual");
    assertThatThrownBy(
            () ->
                tx.executeWithoutResult(
                    s ->
                        jdbc.update(
                            "insert into ledger_transactions(id,tenant_id,payment_intent_id,effect_key,currency) values ('bad','tenant_demo',?,'bad','usd')",
                            p.id())))
        .isInstanceOf(DataIntegrityViolationException.class);
  }

  @Test
  void databaseRejectsBalancedButUnpostedAndAppendAfterPost() {
    PaymentIntent p = create(100, "usd", "manual");
    assertThatThrownBy(
            () ->
                tx.executeWithoutResult(
                    s -> {
                      jdbc.update(
                          "insert into ledger_transactions(id,tenant_id,payment_intent_id,effect_key,currency) values ('unposted','tenant_demo',?,'unposted','usd')",
                          p.id());
                      jdbc.update(
                          "insert into ledger_entries(ledger_transaction_id,account,debit,credit) values ('unposted','a',100,0),('unposted','b',0,100)");
                    }))
        .isInstanceOf(DataIntegrityViolationException.class);
    payments.confirm(p.id());
    payments.capture(p.id(), 100);
    String journal =
        jdbc.queryForObject(
            "select id from ledger_transactions where effect_key=?",
            String.class,
            "capture:" + p.id());
    assertThatThrownBy(
            () ->
                jdbc.update(
                    "insert into ledger_entries(ledger_transaction_id,account,debit,credit) values (?,'late',1,0)",
                    journal))
        .isInstanceOf(DataIntegrityViolationException.class);
  }

  @Test
  void tenantIsolationAndInvalidTransition() {
    PaymentIntent p = create(100, "usd", "automatic");
    jdbc.update(
        "insert into tenants(id,name) values ('tenant_other','Other') on conflict do nothing");
    TenantContext.set("tenant_other");
    assertThatThrownBy(() -> payments.get(p.id()))
        .isInstanceOf(ApiException.class)
        .extracting(e -> ((ApiException) e).status().value())
        .isEqualTo(404);
    TenantContext.set("tenant_demo");
    payments.confirm(p.id());
    assertThatThrownBy(() -> payments.cancel(p.id()))
        .isInstanceOf(ApiException.class)
        .extracting(e -> ((ApiException) e).code())
        .isEqualTo("invalid_state_transition");
  }

  @Test
  void migrationBackfillIsResumableAndReconcilesLiveWrites() {
    create(100, "usd", "manual");
    create(200, "eur", "manual");
    jdbc.execute("truncate payment_intents_v2");
    assertThat(migration.backfill(1)).isEqualTo(1);
    assertThat(migration.backfill(1)).isEqualTo(1);
    assertThat(migration.backfill(1)).isZero();
    assertThat(migration.reconcile())
        .containsEntry("missing", 0L)
        .containsEntry("extra", 0L)
        .containsEntry("mismatched", 0L);
  }

  @Test
  void cutoverPreservesCapturableAndFallsBackFromCorruptTarget() {
    PaymentIntent pending = create(321, "usd", "manual");
    PaymentIntent canceled = create(654, "usd", "manual");
    payments.cancel(canceled.id());
    assertThat(migration.gateCutover()).containsEntry("cutover_ready", true);
    assertThat(payments.get(pending.id()).amountCapturable()).isZero();
    assertThat(payments.get(canceled.id()).amountCapturable()).isZero();
    jdbc.update("update payment_intents_v2 set amount_minor=999 where source_id=?", pending.id());
    PaymentIntent safe = payments.get(pending.id());
    assertThat(safe.amount()).isEqualTo(321);
    assertThat(safe.amountCapturable()).isZero();
  }

  @Test
  void staleOutboxLeaseCannotAcknowledgeNewLease() {
    create(100, "usd", "manual");
    var first = outbox.claim(1).get(0);
    jdbc.update(
        "update outbox_events set lease_until=now()-interval '1 second' where id=?", first.id());
    var second = outbox.claim(1).get(0);
    assertThat(second.leaseToken()).isNotEqualTo(first.leaseToken());
    assertThat(outbox.published(first.id(), first.leaseToken())).isFalse();
    assertThat(outbox.published(second.id(), second.leaseToken())).isTrue();
  }

  @Test
  void providerResponseLossReconcilesWithStableKeyAndUniqueLedger() {
    PaymentIntent p = create(700, "usd", "automatic");
    payments.confirm(p.id());
    String stable = "tenant_demo:" + p.id();
    assertThatThrownBy(() -> provider.authorize(stable))
        .isInstanceOf(SimulatedProvider.ProviderAmbiguousException.class);
    String reference = provider.authorize(stable);
    ProviderCompletion completion =
        new ProviderCompletion("provider-test", "evt-provider", "tenant_demo", p.id(), reference);
    payments.completeProvider(completion);
    payments.completeProvider(completion);
    assertThat(
            jdbc.queryForObject(
                "select count(*) from simulated_provider_operations where stable_key=?",
                Long.class,
                stable))
        .isEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "select count(*) from ledger_transactions where effect_key=?",
                Long.class,
                "capture:" + p.id()))
        .isEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "select provider_reference from payment_intents where id=?", String.class, p.id()))
        .isEqualTo(reference);
  }

  @Test
  void inspectionReturnsSanitizedBalancedHistoryAndHidesOtherTenants() throws Exception {
    PaymentIntent payment = create(700, "usd", "automatic");
    payments.confirm(payment.id());
    String stableKey = "tenant_demo:" + payment.id();
    assertThatThrownBy(() -> provider.authorize(stableKey))
        .isInstanceOf(SimulatedProvider.ProviderAmbiguousException.class);
    String providerReference = provider.authorize(stableKey);
    payments.completeProvider(
        new ProviderCompletion(
            "inspection-test", "evt-inspection", "tenant_demo", payment.id(), providerReference));
    payments.refund(payment.id(), 200);

    http.perform(
            get("/v1/payment_intents/{id}/inspect", payment.id())
                .header("Authorization", "Bearer pr_test_demo"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.paymentIntentId").value(payment.id()))
        .andExpect(jsonPath("$.journals.length()").value(2))
        .andExpect(jsonPath("$.journals[0].posted").value(true))
        .andExpect(jsonPath("$.journals[0].debitTotal").value(700))
        .andExpect(jsonPath("$.journals[0].creditTotal").value(700))
        .andExpect(jsonPath("$.journals[0].balanced").value(true))
        .andExpect(jsonPath("$.journals[0].entries.length()").value(2))
        .andExpect(jsonPath("$.journals[1].debitTotal").value(200))
        .andExpect(jsonPath("$.journals[1].creditTotal").value(200))
        .andExpect(jsonPath("$.journals[1].balanced").value(true))
        .andExpect(jsonPath("$.journals[1].entries.length()").value(2))
        .andExpect(jsonPath("$.events.length()").value(4))
        .andExpect(jsonPath("$.events[0].type").value("payment_intent.created"))
        .andExpect(jsonPath("$.events[0].sequence").value(1))
        .andExpect(jsonPath("$.providerOperations.length()").value(1))
        .andExpect(jsonPath("$.providerOperations[0].reference").value(providerReference))
        .andExpect(jsonPath("$.providerOperations[0].outcome").value("accepted"))
        .andExpect(jsonPath("$..payload").doesNotExist())
        .andExpect(jsonPath("$..stableKey").doesNotExist());

    assertInspectionLedgerBalanced(payment.id());
    assertOtherTenantCannotInspect(payment.id(), providerReference);
  }

  @Test
  void rawReplayKeepsExactVersionedBytesAfterStateChanges() throws Exception {
    var request = new CreateRequest(123, "usd", "manual", null);
    var first =
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                "wire-key",
                "create-wire",
                "2025-01-01",
                request,
                201,
                () -> create(123, "usd", "manual")));
    String id = mapper.readTree(first.body()).path("id").asText();
    payments.confirm(id);
    var replay =
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                "wire-key",
                "create-wire",
                "2025-01-01",
                request,
                201,
                () -> {
                  throw new AssertionError("must replay");
                }));
    assertThat(replay.body())
        .isEqualTo(first.body())
        .contains("\"state\"")
        .doesNotContain("\"status\"");
    assertThat(replay.status()).isEqualTo(201);
    assertThatThrownBy(
            () ->
                idempotency.executeRaw(
                    new IdempotencyService.RawCommand(
                        "wire-key",
                        "create-wire",
                        "2026-01-01",
                        request,
                        201,
                        () -> create(123, "usd", "manual"))))
        .isInstanceOf(ApiException.class);
  }

  @Test
  void concurrencyEvidenceDetectsBrokenNegativeControl() throws Exception {
    var dependencies = new ConcurrencyEvidenceHarness.Dependencies(jdbc, tx, idempotency, mapper);
    var result = new ConcurrencyEvidenceHarness(dependencies).run();
    assertThat(result.guardedActionAttempts()).isEqualTo(1);
    assertThat(result.guardedEffects()).isEqualTo(1);
    assertThat(result.controlEffects()).isEqualTo(ConcurrencyEvidenceHarness.CONCURRENCY);
    assertThat(result.samples()).hasSize(ConcurrencyEvidenceHarness.CONCURRENCY * 2);
  }

  private PaymentIntent create(long amount, String currency, String captureMethod) {
    return payments.create(new CreatePaymentCommand(amount, currency, captureMethod, null));
  }

  private PaymentIntent executePayment(IdempotencyService.RawCommand raw) {
    return idempotency.execute(new IdempotencyService.TypedCommand<>(raw, PaymentIntent.class));
  }

  private void assertInspectionLedgerBalanced(String paymentId) {
    List<Long> balances =
        jdbc.queryForList(
            "select sum(e.debit)-sum(e.credit) from ledger_transactions t join ledger_entries e on e.ledger_transaction_id=t.id where t.tenant_id='tenant_demo' and t.payment_intent_id=? group by t.id",
            Long.class,
            paymentId);
    assertThat(balances).hasSize(2).containsOnly(0L);
  }

  private void assertOtherTenantCannotInspect(String paymentId, String providerReference)
      throws Exception {
    jdbc.update(
        "insert into tenants(id,name) values ('tenant_other','Other') on conflict do nothing");
    jdbc.update(
        "insert into api_keys(tenant_id,key_hash,label) values ('tenant_other',?,'test')",
        apiKeyHasher.hash("pr_test_other"));
    http.perform(
            get("/v1/payment_intents/{id}/inspect", paymentId)
                .header("Authorization", "Bearer pr_test_other"))
        .andExpect(status().isNotFound())
        .andExpect(
            content()
                .string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString(paymentId))))
        .andExpect(
            content()
                .string(
                    org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString(providerReference))));
  }
}
