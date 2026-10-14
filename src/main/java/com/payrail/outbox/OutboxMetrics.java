package com.payrail.outbox;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OutboxMetrics {
  private final JdbcTemplate jdbc;
  private final AtomicLong pending = new AtomicLong();
  private final AtomicReference<Double> oldestSeconds = new AtomicReference<>(0.0);
  private final AtomicLong observedAt = new AtomicLong();
  private final Counter errors;

  public OutboxMetrics(JdbcTemplate jdbc, MeterRegistry registry) {
    this.jdbc = jdbc;
    Gauge.builder("payrail.outbox.pending", pending, AtomicLong::doubleValue).register(registry);
    Gauge.builder("payrail.outbox.oldest.pending.seconds", oldestSeconds, AtomicReference::get)
        .register(registry);
    Gauge.builder(
            "payrail.outbox.observation.timestamp.seconds", observedAt, AtomicLong::doubleValue)
        .register(registry);
    errors = registry.counter("payrail.outbox.observation.errors");
  }

  @Scheduled(fixedDelayString = "${payrail.outbox.metrics-delay-ms:5000}")
  public void observe() {
    try {
      jdbc.query(
          connection -> {
            var statement =
                connection.prepareStatement(
                    """
            select count(*), coalesce(extract(epoch from (now()-min(created_at))),0)
            from outbox_events where published_at is null
            """);
            statement.setQueryTimeout(2);
            return statement;
          },
          result -> {
            if (result.next()) {
              pending.set(result.getLong(1));
              oldestSeconds.set(result.getDouble(2));
              observedAt.set(System.currentTimeMillis() / 1000);
            }
            return null;
          });
    } catch (DataAccessException ex) {
      errors.increment(); // Preserve the last observation; its timestamp exposes stale samples.
    }
  }
}
