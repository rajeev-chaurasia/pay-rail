package com.payrail.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.payrail.api.ApiException;
import com.payrail.auth.TenantContext;
import com.payrail.domain.PaymentIntent;
import com.payrail.domain.PaymentStatus;
import com.payrail.domain.Refund;
import com.payrail.migration.PaymentV2Service;
import com.payrail.persistence.PaymentRepository;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentService {
  private static final Set<String> CURRENCIES = Set.of("usd", "eur", "gbp", "cad", "aud", "jpy");
  private final PaymentRepository repository;
  private final LedgerService ledger;
  private final OutboxService outbox;
  private final PaymentV2Service v2;
  private final Clock clock = Clock.systemUTC();

  public PaymentService(
      PaymentRepository repository,
      LedgerService ledger,
      OutboxService outbox,
      PaymentV2Service v2) {
    this.repository = repository;
    this.ledger = ledger;
    this.outbox = outbox;
    this.v2 = v2;
  }

  @Transactional
  public PaymentIntent create(CreatePaymentCommand command) {
    validateAmount(command.amount());
    String currency = normalizeCurrency(command.currency());
    validateCaptureMethod(command.captureMethod());
    Instant now = clock.instant();
    PaymentIntent payment = newPayment(command, currency, now);
    String tenant = TenantContext.require();
    repository.insert(tenant, payment);
    v2.dualWrite(tenant, payment);
    outbox.append(tenant, payment, "payment_intent.created");
    return payment;
  }

  public PaymentIntent get(String id) {
    String tenant = TenantContext.require();
    PaymentIntent source = repository.find(tenant, id).orElseThrow(this::notFound);
    return v2.resolveRead(tenant, source);
  }

  public List<PaymentIntent> list(String after, int limit) {
    if (limit < 1 || limit > 100)
      throw new ApiException(HttpStatus.BAD_REQUEST, "invalid_limit", "limit must be 1..100");
    return repository.list(TenantContext.require(), after, limit);
  }

  @Transactional
  public PaymentIntent confirm(String id) {
    String tenant = TenantContext.require();
    PaymentIntent old = lock(tenant, id);
    PaymentStatus next =
        old.captureMethod().equals("manual") ? PaymentStatus.AUTHORIZED : PaymentStatus.PROCESSING;
    requireTransition(old, next);
    PaymentIntent p =
        copy(
            old,
            next,
            new PaymentAmounts(
                old.captureMethod().equals("manual") ? old.amount() : 0, 0, old.amountRefunded()));
    repository.update(tenant, p);
    v2.dualWrite(tenant, p);
    outbox.append(
        tenant,
        p,
        old.captureMethod().equals("manual")
            ? "payment_intent.authorized"
            : "provider.authorization.requested");
    return p;
  }

  @Transactional
  public PaymentIntent capture(String id, long amount) {
    String tenant = TenantContext.require();
    PaymentIntent old = lock(tenant, id);
    requireTransition(old, PaymentStatus.SUCCEEDED);
    long capture = amount == 0 ? old.amountCapturable() : amount;
    if (capture <= 0 || capture != old.amountCapturable())
      throw new ApiException(
          HttpStatus.BAD_REQUEST,
          "invalid_capture_amount",
          "this version requires capture of the full capturable amount");
    PaymentIntent p =
        copy(old, PaymentStatus.SUCCEEDED, new PaymentAmounts(0, capture, old.amountRefunded()));
    repository.update(tenant, p);
    ledger.postCapture(tenant, p, capture);
    v2.dualWrite(tenant, p);
    outbox.append(tenant, p, "payment_intent.succeeded");
    return p;
  }

  @Transactional
  public PaymentIntent cancel(String id) {
    String tenant = TenantContext.require();
    PaymentIntent old = lock(tenant, id);
    requireTransition(old, PaymentStatus.CANCELED);
    PaymentIntent p =
        copy(
            old,
            PaymentStatus.CANCELED,
            new PaymentAmounts(0, old.amountReceived(), old.amountRefunded()));
    repository.update(tenant, p);
    v2.dualWrite(tenant, p);
    outbox.append(tenant, p, "payment_intent.canceled");
    return p;
  }

  @Transactional
  public Refund refund(String id, long requested) {
    String tenant = TenantContext.require();
    PaymentIntent old = lock(tenant, id);
    if (old.status() != PaymentStatus.SUCCEEDED && old.status() != PaymentStatus.PARTIALLY_REFUNDED)
      throw invalidTransition(old, PaymentStatus.REFUNDED);
    long remaining = Math.subtractExact(old.amountReceived(), old.amountRefunded());
    long amount = requested == 0 ? remaining : requested;
    if (amount <= 0 || amount > remaining)
      throw new ApiException(
          HttpStatus.BAD_REQUEST, "invalid_refund_amount", "refund exceeds refundable amount");
    long total = Math.addExact(old.amountRefunded(), amount);
    PaymentStatus next =
        total == old.amountReceived() ? PaymentStatus.REFUNDED : PaymentStatus.PARTIALLY_REFUNDED;
    PaymentIntent p = copy(old, next, new PaymentAmounts(0, old.amountReceived(), total));
    repository.update(tenant, p);
    String rid = "re_" + UUID.randomUUID().toString().replace("-", "");
    repository.insertRefund(tenant, rid, id, amount);
    ledger.postRefund(tenant, p, rid, amount);
    v2.dualWrite(tenant, p);
    outbox.append(tenant, p, "payment_intent." + next.wire());
    return new Refund(rid, id, amount, "succeeded", clock.instant());
  }

  private PaymentIntent lock(String tenant, String id) {
    return repository.lock(tenant, id).orElseThrow(this::notFound);
  }

  private void requireTransition(PaymentIntent p, PaymentStatus next) {
    if (!p.status().canTransitionTo(next)) throw invalidTransition(p, next);
  }

  private ApiException invalidTransition(PaymentIntent p, PaymentStatus next) {
    return new ApiException(
        HttpStatus.CONFLICT,
        "invalid_state_transition",
        "cannot transition " + p.status().wire() + " to " + next.wire());
  }

  private ApiException notFound() {
    return new ApiException(
        HttpStatus.NOT_FOUND, "payment_intent_not_found", "Payment intent was not found");
  }

  private PaymentIntent copy(PaymentIntent p, PaymentStatus status, PaymentAmounts amounts) {
    return new PaymentIntent(
        p.id(),
        p.amount(),
        amounts.capturable(),
        amounts.received(),
        amounts.refunded(),
        p.currency(),
        p.captureMethod(),
        status,
        p.version() + 1,
        p.metadata(),
        p.createdAt(),
        clock.instant());
  }

  @Transactional
  public void completeProvider(ProviderCompletion completion) {
    if (!repository.recordProcessedEvent(completion.consumer(), completion.eventId())) return;
    PaymentIntent old =
        repository.lock(completion.tenantId(), completion.paymentId()).orElseThrow(this::notFound);
    if (old.status() != PaymentStatus.PROCESSING) return;
    requireTransition(old, PaymentStatus.SUCCEEDED);
    PaymentAmounts amounts = new PaymentAmounts(0, old.amount(), old.amountRefunded());
    PaymentIntent payment = copy(old, PaymentStatus.SUCCEEDED, amounts);
    repository.update(completion.tenantId(), payment);
    repository.saveProviderReference(
        completion.tenantId(), completion.paymentId(), completion.providerReference());
    ledger.postCapture(completion.tenantId(), payment, payment.amount());
    v2.dualWrite(completion.tenantId(), payment);
    outbox.append(completion.tenantId(), payment, "payment_intent.succeeded");
  }

  private PaymentIntent newPayment(
      CreatePaymentCommand command, String currency, Instant createdAt) {
    String id = newPaymentId(createdAt);
    JsonNode metadata =
        command.metadata() == null ? JsonNodeFactory.instance.objectNode() : command.metadata();
    return new PaymentIntent(
        id,
        command.amount(),
        0,
        0,
        0,
        currency,
        command.captureMethod(),
        PaymentStatus.REQUIRES_CONFIRMATION,
        1,
        metadata,
        createdAt,
        createdAt);
  }

  private String newPaymentId(Instant createdAt) {
    String random = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    return "pi_" + Long.toString(createdAt.toEpochMilli(), 36) + random;
  }

  private void validateAmount(long amount) {
    if (amount <= 0 || amount > 999_999_999_999L) {
      throw new ApiException(
          HttpStatus.BAD_REQUEST,
          "invalid_amount",
          "amount must be a positive bounded integer in minor units");
    }
  }

  private String normalizeCurrency(String currency) {
    String normalized = currency.toLowerCase(Locale.ROOT);
    if (!CURRENCIES.contains(normalized)) {
      throw new ApiException(
          HttpStatus.BAD_REQUEST, "unsupported_currency", "currency is not supported");
    }
    return normalized;
  }

  private void validateCaptureMethod(String captureMethod) {
    if (!Set.of("automatic", "manual").contains(captureMethod)) {
      throw new ApiException(
          HttpStatus.BAD_REQUEST,
          "invalid_capture_method",
          "capture_method must be automatic or manual");
    }
  }

  private record PaymentAmounts(long capturable, long received, long refunded) {}
}
