package com.payrail.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.payrail.domain.PaymentIntent;
import com.payrail.service.CreatePaymentCommand;
import com.payrail.service.IdempotencyService;
import com.payrail.service.PaymentService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@Validated
@RestController
@RequestMapping("/v1/payment_intents")
public class PaymentController {
  private final PaymentService payments;
  private final IdempotencyService idempotency;
  private final WireResponseRegistry wire;

  public PaymentController(
      PaymentService payments, IdempotencyService idempotency, WireResponseRegistry wire) {
    this.payments = payments;
    this.idempotency = idempotency;
    this.wire = wire;
  }

  public record CreateRequest(
      @Min(1) long amount, @NotBlank String currency, String captureMethod, JsonNode metadata) {
    public CreateRequest {
      if (captureMethod == null) captureMethod = "automatic";
    }
  }

  public record AmountRequest(@Min(0) long amount) {}

  @PostMapping
  public ResponseEntity<String> create(
      @RequestHeader("Idempotency-Key") String key,
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version,
      @Valid @RequestBody CreateRequest r) {
    return response(
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                key,
                "payment_intents.create",
                version,
                r,
                201,
                () ->
                    payments.create(
                        new CreatePaymentCommand(
                            r.amount(), r.currency(), r.captureMethod(), r.metadata())))));
  }

  @GetMapping("/{id}")
  public ResponseEntity<String> get(
      @PathVariable String id,
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version) {
    wire.validate(version);
    return ResponseEntity.ok()
        .contentType(MediaType.APPLICATION_JSON)
        .header("PayRail-Version", version)
        .body(wire.serialize(version, payments.get(id)));
  }

  @GetMapping
  public ResponseEntity<String> list(
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version,
      @RequestParam(required = false) String after,
      @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit) {
    List<PaymentIntent> data = payments.list(after, limit);
    return ResponseEntity.ok()
        .contentType(MediaType.APPLICATION_JSON)
        .header("PayRail-Version", version)
        .body(
            wire.serialize(
                version,
                Map.of(
                    "data",
                    data,
                    "next_cursor",
                    data.size() == limit ? data.get(data.size() - 1).id() : "")));
  }

  @PostMapping("/{id}/confirm")
  public ResponseEntity<String> confirm(
      @PathVariable String id,
      @RequestHeader("Idempotency-Key") String key,
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version) {
    return response(
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                key,
                "payment_intents.confirm:" + id,
                version,
                Map.of("id", id),
                202,
                () -> payments.confirm(id))));
  }

  @PostMapping("/{id}/capture")
  public ResponseEntity<String> capture(
      @PathVariable String id,
      @RequestHeader("Idempotency-Key") String key,
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version,
      @RequestBody(required = false) AmountRequest body) {
    long amount = body == null ? 0 : body.amount();
    return response(
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                key,
                "payment_intents.capture:" + id,
                version,
                Map.of("id", id, "amount", amount),
                200,
                () -> payments.capture(id, amount))));
  }

  @PostMapping("/{id}/cancel")
  public ResponseEntity<String> cancel(
      @PathVariable String id,
      @RequestHeader("Idempotency-Key") String key,
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version) {
    return response(
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                key,
                "payment_intents.cancel:" + id,
                version,
                Map.of("id", id),
                200,
                () -> payments.cancel(id))));
  }

  @PostMapping("/{id}/refunds")
  public ResponseEntity<String> refund(
      @PathVariable String id,
      @RequestHeader("Idempotency-Key") String key,
      @RequestHeader(value = "PayRail-Version", defaultValue = "2026-01-01") String version,
      @RequestBody(required = false) AmountRequest body) {
    long amount = body == null ? 0 : body.amount();
    return response(
        idempotency.executeRaw(
            new IdempotencyService.RawCommand(
                key,
                "payment_intents.refund:" + id,
                version,
                Map.of("id", id, "amount", amount),
                200,
                () -> payments.refund(id, amount))));
  }

  private ResponseEntity<String> response(IdempotencyService.PinnedResponse response) {
    return ResponseEntity.status(response.status())
        .contentType(MediaType.APPLICATION_JSON)
        .header("PayRail-Version", response.apiVersion())
        .body(response.body());
  }
}
