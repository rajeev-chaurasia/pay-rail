package com.payrail.outbox;

import java.util.function.Supplier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class ConsumerInbox {
  private final JdbcTemplate jdbc;

  public ConsumerInbox(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  @Transactional
  public <T> T once(String consumer, String eventId, Supplier<T> effect) {
    int n =
        jdbc.update(
            "insert into processed_events(consumer_name,event_id) values (?,?) on conflict do nothing",
            consumer,
            eventId);
    return n == 0 ? null : effect.get();
  }
}
