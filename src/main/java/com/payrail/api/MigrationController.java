package com.payrail.api;

import com.payrail.config.PayRailProperties;
import com.payrail.migration.PaymentV2Service;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1/admin/migrations/payment-v2")
public class MigrationController {
  private final PaymentV2Service migration;
  private final String token;

  public MigrationController(PaymentV2Service migration, PayRailProperties p) {
    this.migration = migration;
    this.token = p.migration().adminToken();
  }

  @GetMapping
  public Map<String, Object> status(@RequestHeader("X-Admin-Token") String supplied) {
    auth(supplied);
    return migration.status();
  }

  @GetMapping("/reconcile")
  public Map<String, Object> reconcile(@RequestHeader("X-Admin-Token") String supplied) {
    auth(supplied);
    return migration.reconcile();
  }

  @PostMapping("/backfill")
  public Map<String, Object> backfill(
      @RequestHeader("X-Admin-Token") String supplied,
      @RequestParam(defaultValue = "500") int batchSize) {
    auth(supplied);
    if (batchSize < 1 || batchSize > 5000)
      throw new ApiException(
          HttpStatus.BAD_REQUEST, "invalid_batch_size", "batch size must be 1..5000");
    return Map.of("processed", migration.backfill(batchSize));
  }

  @PostMapping("/gate-cutover")
  public Map<String, Object> gate(@RequestHeader("X-Admin-Token") String supplied) {
    auth(supplied);
    return migration.gateCutover();
  }

  private void auth(String supplied) {
    if (!java.security.MessageDigest.isEqual(
        token.getBytes(java.nio.charset.StandardCharsets.UTF_8),
        supplied.getBytes(java.nio.charset.StandardCharsets.UTF_8)))
      throw new ApiException(
          HttpStatus.UNAUTHORIZED, "invalid_admin_token", "Invalid migration admin token");
  }
}
