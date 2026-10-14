package com.payrail;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
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
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers
@AutoConfigureMockMvc
@org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability
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
  void httpCreateBoundaryRejectsBadAuthKeysVersionsAndFields() throws Exception {
    http.perform(post("/v1/payment_intents")).andExpect(status().isUnauthorized());
    http.perform(
            post("/v1/payment_intents")
                .header("Authorization", "Bearer invalid")
                .header("Idempotency-Key", "x")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"amount\":100,\"currency\":\"usd\"}"))
        .andExpect(status().isUnauthorized());
    http.perform(
            auth(post("/v1/payment_intents"))
                .contentType(MediaType.APPLICATION_JSON)
                .content(validCreate()))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.error.code").value("invalid_request"));
    assertCreateRejected("", "2026-01-01", validCreate(), 400, "invalid_idempotency_key");
    assertCreateRejected(
        "unknown-version", "2099-01-01", validCreate(), 400, "unsupported_api_version");
    assertCreateRejected("zero", "2026-01-01", createBody(0, "usd", "manual", "{}"), 400, null);
    assertCreateRejected(
        "too-large",
        "2026-01-01",
        createBody(1_000_000_000_000L, "usd", "manual", "{}"),
        400,
        "invalid_amount");
    assertCreateRejected(
        "currency",
        "2026-01-01",
        createBody(100, "xyz", "manual", "{}"),
        400,
        "unsupported_currency");
    assertCreateRejected(
        "capture",
        "2026-01-01",
        createBody(100, "usd", "partial", "{}"),
        400,
        "invalid_capture_method");
    assertCreateRejected(
        "metadata", "2026-01-01", createBody(100, "usd", "manual", "[]"), 400, "invalid_metadata");
    assertCreateRejected("malformed", "2026-01-01", "{", 400, null);

    jdbc.update("update api_keys set enabled=false where tenant_id='tenant_demo'");
    try {
      assertCreateRejected("disabled", "2026-01-01", validCreate(), 401, "invalid_api_key");
    } finally {
      jdbc.update("update api_keys set enabled=true where tenant_id='tenant_demo'");
    }
  }

  @Test
  void httpLifecyclePaginationAndVersionTransforms() throws Exception {
    String first = httpCreate("lifecycle-1", createBody(500, "usd", "manual", "{\"order\":1}"));
    String second = httpCreate("lifecycle-2", createBody(600, "usd", "manual", "{}"));

    http.perform(
            auth(get("/v1/payment_intents/{id}", first)).header("PayRail-Version", "2025-01-01"))
        .andExpect(status().isOk())
        .andExpect(header().string("PayRail-Version", "2025-01-01"))
        .andExpect(jsonPath("$.state").value("requires_confirmation"))
        .andExpect(jsonPath("$.status").doesNotExist());
    String firstPage =
        http.perform(auth(get("/v1/payment_intents")).param("limit", "1"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data.length()").value(1))
            .andExpect(jsonPath("$.next_cursor").isNotEmpty())
            .andReturn()
            .getResponse()
            .getContentAsString();
    String firstPageId = mapper.readTree(firstPage).path("data").get(0).path("id").asText();
    String cursor = mapper.readTree(firstPage).path("next_cursor").asText();
    String secondPage =
        http.perform(
                auth(get("/v1/payment_intents"))
                    .header("PayRail-Version", "2025-01-01")
                    .param("limit", "1")
                    .param("after", cursor))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data[0].id").value(org.hamcrest.Matchers.not(firstPageId)))
            .andExpect(jsonPath("$.data[0].state").value("requires_confirmation"))
            .andExpect(jsonPath("$.data[0].status").doesNotExist())
            .andReturn()
            .getResponse()
            .getContentAsString();
    String terminalCursor = mapper.readTree(secondPage).path("next_cursor").asText();
    http.perform(
            auth(get("/v1/payment_intents")).param("limit", "1").param("after", terminalCursor))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.data.length()").value(0));
    http.perform(auth(get("/v1/payment_intents")).param("limit", "101"))
        .andExpect(status().isBadRequest());

    http.perform(action(first, "confirm", "confirm-1", null)).andExpect(status().isAccepted());
    http.perform(action(first, "capture", "partial-capture", "{\"amount\":200}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.error.code").value("invalid_capture_amount"));
    http.perform(action(first, "capture", "full-capture", "{}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("succeeded"));
    http.perform(action(first, "capture", "double-capture", "{}")).andExpect(status().isConflict());
    http.perform(action(second, "cancel", "confirm-1", null))
        .andExpect(status().isConflict())
        .andExpect(jsonPath("$.error.code").value("idempotency_conflict"));
    http.perform(action(second, "cancel", "cancel-1", null))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("canceled"));
    http.perform(action(second, "confirm", "confirm-canceled", null))
        .andExpect(status().isConflict());
    assertThat(jdbc.queryForObject("select count(*) from ledger_transactions", Long.class))
        .isEqualTo(1);
  }

  @Test
  void refundReplayAndConcurrentOversubscriptionPreserveCapturedTotal() throws Exception {
    PaymentIntent payment = create(1000, "usd", "manual");
    payments.confirm(payment.id());
    payments.capture(payment.id(), 1000);
    String path = "/v1/payment_intents/" + payment.id() + "/refunds";
    String first =
        http.perform(
                auth(post(path))
                    .header("Idempotency-Key", "refund-replay")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"amount\":200}"))
            .andExpect(status().isOk())
            .andReturn()
            .getResponse()
            .getContentAsString();
    http.perform(
            auth(post(path))
                .header("Idempotency-Key", "refund-replay")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"amount\":200}"))
        .andExpect(status().isOk())
        .andExpect(content().string(first));

    CyclicBarrier barrier = new CyclicBarrier(2);
    var pool = Executors.newFixedThreadPool(2);
    List<Callable<Boolean>> calls = new ArrayList<>();
    for (int worker = 0; worker < 2; worker++) {
      calls.add(
          () -> {
            TenantContext.set("tenant_demo");
            try {
              barrier.await();
              payments.refund(payment.id(), 500);
              return true;
            } catch (ApiException e) {
              assertThat(e.code()).isEqualTo("invalid_refund_amount");
              assertThat(e.status().value()).isEqualTo(400);
              return false;
            } finally {
              TenantContext.clear();
            }
          });
    }
    var results = pool.invokeAll(calls);
    pool.shutdown();
    assertThat(results).extracting(f -> f.get()).containsExactlyInAnyOrder(true, false);
    TenantContext.set("tenant_demo");
    assertThat(payments.get(payment.id()).amountRefunded()).isEqualTo(700);
    assertThat(jdbc.queryForObject("select sum(amount) from refunds", Long.class)).isEqualTo(700);
    assertThat(jdbc.queryForObject("select sum(debit)-sum(credit) from ledger_entries", Long.class))
        .isZero();
    payments.refund(payment.id(), 300);
    assertThat(payments.get(payment.id()).status().wire()).isEqualTo("refunded");
    assertThatThrownBy(() -> payments.refund(payment.id(), 1))
        .isInstanceOf(ApiException.class)
        .extracting(e -> ((ApiException) e).code())
        .isEqualTo("invalid_state_transition");
  }

  @Test
  void migrationAdminAuthBoundsAndDivergenceGateAreEnforced() throws Exception {
    http.perform(get("/v1/admin/migrations/payment-v2")).andExpect(status().isBadRequest());
    http.perform(get("/v1/admin/migrations/payment-v2").header("X-Admin-Token", "wrong"))
        .andExpect(status().isUnauthorized());
    http.perform(
            post("/v1/admin/migrations/payment-v2/backfill")
                .header("X-Admin-Token", "local-admin-token")
                .param("batchSize", "0"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.error.code").value("invalid_batch_size"));
    PaymentIntent payment = create(100, "usd", "manual");
    jdbc.update("update payment_intents_v2 set amount_minor=101 where source_id=?", payment.id());
    http.perform(
            post("/v1/admin/migrations/payment-v2/gate-cutover")
                .header("X-Admin-Token", "local-admin-token"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.mismatched").value(1))
        .andExpect(jsonPath("$.cutover_ready").value(false));
    assertThat(payments.get(payment.id()).amount()).isEqualTo(100);
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
    assertThatThrownBy(
            () ->
                tx.executeWithoutResult(
                    ignored -> {
                      jdbc.update(
                          "insert into ledger_transactions(id,tenant_id,payment_intent_id,effect_key,currency) values ('unbalanced','tenant_demo',?,'unbalanced','usd')",
                          p.id());
                      jdbc.update(
                          "insert into ledger_entries(ledger_transaction_id,account,debit,credit) values ('unbalanced','provider_clearing',100,0)");
                      jdbc.update(
                          "insert into ledger_entries(ledger_transaction_id,account,debit,credit) values ('unbalanced','merchant_payable',0,99)");
                      jdbc.update(
                          "update ledger_transactions set posted=true where id='unbalanced'");
                    }))
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
  void databaseRejectsCrossTenantPaymentEffects() {
    PaymentIntent payment = create(100, "usd", "manual");
    jdbc.update(
        "insert into tenants(id,name) values ('tenant_other','Other') on conflict do nothing");
    assertThatThrownBy(
            () ->
                jdbc.update(
                    "insert into refunds(id,tenant_id,payment_intent_id,amount,status) values ('cross','tenant_other',?,1,'succeeded')",
                    payment.id()))
        .isInstanceOf(DataIntegrityViolationException.class);
    assertThatThrownBy(
            () ->
                tx.executeWithoutResult(
                    ignored ->
                        jdbc.update(
                            "insert into ledger_transactions(id,tenant_id,payment_intent_id,effect_key,currency) values ('cross','tenant_other',?,'cross','usd')",
                            payment.id())))
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
  void prometheusExposesPersistedBacklogAndObservationFreshness() throws Exception {
    create(100, "usd", "manual");
    var registry = new io.micrometer.core.instrument.simple.SimpleMeterRegistry();
    var metrics = new com.payrail.outbox.OutboxMetrics(jdbc, registry);
    metrics.observe();
    assertThat(registry.get("payrail.outbox.pending").gauge().value()).isEqualTo(1.0);
    assertThat(registry.get("payrail.outbox.observation.timestamp.seconds").gauge().value())
        .isPositive();
    http.perform(get("/actuator/prometheus")).andExpect(status().isOk());
  }

  @Test
  void productionGuardRejectsOwnerAndAcceptsRestrictedRoleOnRealPostgres() {
    var environment =
        new org.springframework.mock.env.MockEnvironment()
            .withProperty("spring.flyway.enabled", "false")
            .withProperty(
                "spring.datasource.url", "jdbc:postgresql://db/payrail?sslmode=verify-full")
            .withProperty("spring.data.redis.ssl.enabled", "true")
            .withProperty("spring.data.redis.password", "synthetic-test-secret")
            .withProperty("spring.kafka.properties.security.protocol", "SSL");
    environment.setActiveProfiles("prod");
    var config =
        new com.payrail.config.PayRailProperties(
            new com.payrail.config.PayRailProperties.Auth(
                "synthetic-pepper-for-test-only-0123456789"),
            new com.payrail.config.PayRailProperties.RateLimit(true, 600),
            new com.payrail.config.PayRailProperties.Outbox(true, 100, 250),
            new com.payrail.config.PayRailProperties.Migration(
                true, 0, 0, "synthetic-admin-for-test-only-0123456789"));
    var guard = new com.payrail.config.ProductionSecretGuard(environment, config, jdbc);
    assertThatThrownBy(() -> guard.run(null)).hasMessageContaining("non-owner database role");
    tx.executeWithoutResult(
        status -> {
          jdbc.execute(
              "create role restricted_guard_test nologin nosuperuser nocreatedb nocreaterole nobypassrls");
          jdbc.execute("set local role restricted_guard_test");
          guard.run(null);
          status.setRollbackOnly();
        });
  }

  @Test
  void restrictedRuntimeGrantsSupportLifecycleWithoutDdlOrLedgerDeletes() throws Exception {
    String script =
        java.nio.file.Files.readString(java.nio.file.Path.of("deploy/postgres-runtime-role.sql"));
    String grants =
        script.replace("\\set ON_ERROR_STOP on", "").replace("begin;", "").replace("commit;", "");
    tx.executeWithoutResult(
        status -> {
          jdbc.execute(grants);
          jdbc.execute("set local role payrail_runtime");
          var payment = create(100, "usd", "manual");
          payments.confirm(payment.id());
          payments.capture(payment.id(), 100L);
          payments.refund(payment.id(), 100);
          assertThat(payments.get(payment.id()).status().wire()).isEqualTo("refunded");
          assertThat(migration.backfill(500)).isEqualTo(1);
          assertThat(migration.reconcile()).containsEntry("mismatched", 0L);
          var event = outbox.claim(100).get(0);
          assertThat(outbox.published(event.id(), event.leaseToken())).isTrue();
          assertThat(
                  jdbc.queryForObject(
                      "select has_schema_privilege(current_user,'public','CREATE')", Boolean.class))
              .isFalse();
          assertThat(
                  jdbc.queryForObject(
                      "select has_table_privilege(current_user,'ledger_entries','DELETE')",
                      Boolean.class))
              .isFalse();
          status.setRollbackOnly();
        });
  }

  @Test
  void historicalBatchBackfillRollsBackCheckpointAndResumesWithLiveWrites() {
    jdbc.update(
        """
        insert into payment_intents(id,tenant_id,amount,currency,capture_method,status,version)
        select 'pi_historical_'||lpad(n::text,8,'0'),'tenant_demo',100+n,'usd','manual',
          'requires_confirmation',1 from generate_series(1,10000) n
        """);
    tx.executeWithoutResult(
        status -> {
          assertThat(migration.backfill(500)).isEqualTo(500);
          status.setRollbackOnly();
        });
    assertThat(jdbc.queryForObject("select count(*) from payment_intents_v2", Long.class)).isZero();
    assertThat(migration.status()).containsEntry("rows_processed", 0L);
    assertThat(migration.backfill(500)).isEqualTo(500);
    var live = create(321, "usd", "manual");
    payments.confirm(live.id());
    int remaining = 0;
    int batch;
    while ((batch = migration.backfill(500)) > 0) remaining += batch;
    assertThat(remaining).isEqualTo(9501);
    assertThat(migration.reconcile())
        .containsEntry("missing", 0L)
        .containsEntry("extra", 0L)
        .containsEntry("mismatched", 0L)
        .containsEntry("source_total", 10001L)
        .containsEntry("target_total", 10001L);
    assertThat(migration.gateCutover()).containsEntry("cutover_ready", true);
    assertThat(payments.get(live.id()).status().wire()).isEqualTo("authorized");
  }

  @Test
  void repeatedProviderRedeliveryDoesNotDuplicateMoney() {
    var payment = create(700, "usd", "automatic");
    payments.confirm(payment.id());
    String stable = "tenant_demo:" + payment.id();
    assertThatThrownBy(() -> provider.authorize(stable))
        .isInstanceOf(SimulatedProvider.ProviderAmbiguousException.class);
    String reference = provider.authorize(stable);
    var completion =
        new ProviderCompletion(
            "campaign", "campaign-event", "tenant_demo", payment.id(), reference);
    for (int attempt = 0; attempt < 10000; attempt++) payments.completeProvider(completion);
    assertThat(jdbc.queryForObject("select count(*) from ledger_transactions", Long.class))
        .isEqualTo(1);
    assertThat(jdbc.queryForObject("select sum(debit)-sum(credit) from ledger_entries", Long.class))
        .isZero();
    assertThat(payments.get(payment.id()).amountReceived()).isEqualTo(700);
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
  void batchClaimsOnlyIndependentAggregateHeadsAndFencesConcurrentWorkers() throws Exception {
    var first = create(100, "usd", "manual");
    payments.confirm(first.id());
    for (int i = 0; i < 30; i++) create(100 + i, "usd", "manual");
    var pool = java.util.concurrent.Executors.newFixedThreadPool(2);
    try {
      var start = new java.util.concurrent.CyclicBarrier(2);
      var results =
          pool.invokeAll(
              java.util.List
                  .<java.util.concurrent.Callable<java.util.List<OutboxRepository.Event>>>of(
                      () -> {
                        start.await();
                        return outbox.claim(20);
                      },
                      () -> {
                        start.await();
                        return outbox.claim(20);
                      }));
      var claimed = new java.util.ArrayList<OutboxRepository.Event>();
      for (var result : results) claimed.addAll(result.get());
      assertThat(claimed).hasSize(31);
      assertThat(claimed.stream().map(OutboxRepository.Event::id).distinct().count()).isEqualTo(31);
      assertThat(claimed.stream().filter(e -> e.aggregateId().equals(first.id())))
          .hasSize(1)
          .allMatch(e -> e.sequence() == 1);
      assertThat(outbox.claim(100)).isEmpty();
      for (var event : claimed)
        assertThat(outbox.published(event.id(), event.leaseToken())).isTrue();
      assertThat(outbox.claim(100))
          .singleElement()
          .satisfies(e -> assertThat(e.aggregateId()).isEqualTo(first.id()));
    } finally {
      pool.shutdownNow();
    }
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

  private MockHttpServletRequestBuilder auth(MockHttpServletRequestBuilder request) {
    return request.header("Authorization", "Bearer pr_test_demo");
  }

  private MockHttpServletRequestBuilder action(
      String paymentId, String action, String key, String body) {
    MockHttpServletRequestBuilder request =
        auth(post("/v1/payment_intents/{id}/{action}", paymentId, action))
            .header("Idempotency-Key", key);
    return body == null ? request : request.contentType(MediaType.APPLICATION_JSON).content(body);
  }

  private String httpCreate(String key, String body) throws Exception {
    String response =
        http.perform(
                auth(post("/v1/payment_intents"))
                    .header("Idempotency-Key", key)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(body))
            .andExpect(status().isCreated())
            .andReturn()
            .getResponse()
            .getContentAsString();
    return mapper.readTree(response).path("id").asText();
  }

  private void assertCreateRejected(
      String key, String version, String body, int expectedStatus, String expectedCode)
      throws Exception {
    var result =
        http.perform(
                auth(post("/v1/payment_intents"))
                    .header("Idempotency-Key", key)
                    .header("PayRail-Version", version)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(body))
            .andExpect(status().is(expectedStatus));
    if (expectedCode != null) result.andExpect(jsonPath("$.error.code").value(expectedCode));
  }

  private String validCreate() {
    return createBody(100, "usd", "manual", "{}");
  }

  private String createBody(long amount, String currency, String captureMethod, String metadata) {
    return "{\"amount\":"
        + amount
        + ",\"currency\":\""
        + currency
        + "\",\"captureMethod\":\""
        + captureMethod
        + "\",\"metadata\":"
        + metadata
        + "}";
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
    http.perform(
            post("/v1/payment_intents/{id}/confirm", paymentId)
                .header("Authorization", "Bearer pr_test_other")
                .header("Idempotency-Key", "other-confirm"))
        .andExpect(status().isNotFound())
        .andExpect(
            content()
                .string(
                    org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString(paymentId))));
  }
}
