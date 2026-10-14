package com.payrail.outbox;

import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.support.TransactionTemplate;

@Repository
public class OutboxRepository {
  public record Event(
      String id,
      String aggregateId,
      long sequence,
      String eventType,
      String payload,
      String leaseToken) {}

  private final JdbcTemplate jdbc;
  private final TransactionTemplate transactions;

  public OutboxRepository(JdbcTemplate jdbc, TransactionTemplate transactions) {
    this.jdbc = jdbc;
    this.transactions = transactions;
  }

  public List<Event> claim(int size) {
    int batchSize = Math.max(1, Math.min(size, 100));
    return transactions.execute(
        s -> {
          List<Event> base =
              jdbc.query(
                  "select e.id,e.aggregate_id,e.aggregate_sequence,e.event_type,e.payload::text from outbox_events e where e.published_at is null and e.available_at<=now() and (e.lease_until is null or e.lease_until<=now()) and not exists(select 1 from outbox_events prior where prior.aggregate_id=e.aggregate_id and prior.aggregate_sequence<e.aggregate_sequence and prior.published_at is null) order by e.created_at limit ? for update of e skip locked",
                  (rs, n) ->
                      new Event(
                          rs.getString(1),
                          rs.getString(2),
                          rs.getLong(3),
                          rs.getString(4),
                          rs.getString(5),
                          null),
                  batchSize);
          return base.stream()
              .map(
                  e -> {
                    String token = UUID.randomUUID().toString();
                    jdbc.update(
                        "update outbox_events set attempts=attempts+1,lease_token=?,lease_until=now()+interval '30 seconds' where id=?",
                        token,
                        e.id());
                    return new Event(
                        e.id(), e.aggregateId(), e.sequence(), e.eventType(), e.payload(), token);
                  })
              .toList();
        });
  }

  public boolean published(String id, String token) {
    return jdbc.update(
            "update outbox_events set published_at=now(),last_error=null,lease_token=null,lease_until=null where id=? and published_at is null and lease_token=?",
            id,
            token)
        == 1;
  }

  public boolean failed(String id, String token, String error) {
    return jdbc.update(
            "update outbox_events set last_error=?,available_at=now()+least(interval '5 minutes', interval '1 second' * power(2,least(attempts,8))),lease_token=null,lease_until=null where id=? and published_at is null and lease_token=?",
            error.substring(0, Math.min(error.length(), 1000)),
            id,
            token)
        == 1;
  }
}
