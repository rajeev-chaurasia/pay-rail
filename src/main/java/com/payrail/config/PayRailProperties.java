package com.payrail.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("payrail")
public record PayRailProperties(
    Auth auth, RateLimit rateLimit, Outbox outbox, Migration migration) {
  public record Auth(String pepper) {}

  public record RateLimit(boolean enabled, int requestsPerMinute) {}

  public record Outbox(boolean enabled, int batchSize, long fixedDelayMs) {}

  public record Migration(
      boolean dualWrite, int shadowReadPercent, int v2ReadPercent, String adminToken) {}
}
