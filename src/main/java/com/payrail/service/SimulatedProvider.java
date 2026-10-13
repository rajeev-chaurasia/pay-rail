package com.payrail.service;

import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class SimulatedProvider {
  private final JdbcTemplate jdbc;
  private final int failEvery;
  private final AtomicLong calls = new AtomicLong();
  private final java.util.Set<String> faulted = ConcurrentHashMap.newKeySet();

  public SimulatedProvider(
      JdbcTemplate jdbc, @Value("${payrail.provider.fail-after-accept-every:0}") int failEvery) {
    this.jdbc = jdbc;
    this.failEvery = failEvery;
  }

  public String authorize(String stableKey) {
    String proposed = "prov_" + UUID.randomUUID().toString().replace("-", "");
    jdbc.update(
        "insert into simulated_provider_operations(stable_key,provider_reference,status) values (?,?,'accepted') on conflict(stable_key) do nothing",
        stableKey,
        proposed);
    String reference =
        jdbc.queryForObject(
            "select provider_reference from simulated_provider_operations where stable_key=?",
            String.class,
            stableKey);
    if (failEvery > 0 && calls.incrementAndGet() % failEvery == 0 && faulted.add(stableKey))
      throw new ProviderAmbiguousException("simulated response loss after provider acceptance");
    return reference;
  }

  public static class ProviderAmbiguousException extends RuntimeException {
    public ProviderAmbiguousException(String message) {
      super(message);
    }
  }
}
