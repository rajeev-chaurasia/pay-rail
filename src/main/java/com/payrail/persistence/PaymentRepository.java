package com.payrail.persistence;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.payrail.domain.PaymentIntent;
import com.payrail.domain.PaymentStatus;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class PaymentRepository {
  private final JdbcTemplate jdbc;
  private final ObjectMapper mapper;

  public PaymentRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
    this.jdbc = jdbc;
    this.mapper = mapper;
  }

  public void insert(String tenant, PaymentIntent p) {
    jdbc.update(
        "insert into payment_intents(id,tenant_id,amount,amount_capturable,amount_received,amount_refunded,currency,capture_method,status,version,metadata,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?::jsonb,?,?)",
        p.id(),
        tenant,
        p.amount(),
        p.amountCapturable(),
        p.amountReceived(),
        p.amountRefunded(),
        p.currency(),
        p.captureMethod(),
        p.status().wire(),
        p.version(),
        json(p.metadata()),
        java.sql.Timestamp.from(p.createdAt()),
        java.sql.Timestamp.from(p.updatedAt()));
  }

  public Optional<PaymentIntent> find(String tenant, String id) {
    return jdbc
        .query("select * from payment_intents where tenant_id=? and id=?", this::map, tenant, id)
        .stream()
        .findFirst();
  }

  public Optional<PaymentIntent> lock(String tenant, String id) {
    return jdbc
        .query(
            "select * from payment_intents where tenant_id=? and id=? for update",
            this::map,
            tenant,
            id)
        .stream()
        .findFirst();
  }

  public void update(String tenant, PaymentIntent p) {
    int changed =
        jdbc.update(
            "update payment_intents set amount_capturable=?,amount_received=?,amount_refunded=?,status=?,version=?,updated_at=? where tenant_id=? and id=?",
            p.amountCapturable(),
            p.amountReceived(),
            p.amountRefunded(),
            p.status().wire(),
            p.version(),
            java.sql.Timestamp.from(p.updatedAt()),
            tenant,
            p.id());
    if (changed != 1) throw new IllegalStateException("payment update lost");
  }

  public void insertRefund(String tenant, String refundId, String paymentId, long amount) {
    jdbc.update(
        "insert into refunds(id,tenant_id,payment_intent_id,amount,status) values (?,?,?,?, 'succeeded')",
        refundId,
        tenant,
        paymentId,
        amount);
  }

  public boolean recordProcessedEvent(String consumer, String eventId) {
    return jdbc.update(
            "insert into processed_events(consumer_name,event_id) values (?,?) on conflict do nothing",
            consumer,
            eventId)
        == 1;
  }

  public void saveProviderReference(String tenant, String paymentId, String reference) {
    jdbc.update(
        "update payment_intents set provider_reference=? where tenant_id=? and id=?",
        reference,
        tenant,
        paymentId);
  }

  public List<PaymentIntent> list(String tenant, String after, int limit) {
    return after == null
        ? jdbc.query(
            "select * from payment_intents where tenant_id=? order by id limit ?",
            this::map,
            tenant,
            limit)
        : jdbc.query(
            "select * from payment_intents where tenant_id=? and id>? order by id limit ?",
            this::map,
            tenant,
            after,
            limit);
  }

  private PaymentIntent map(ResultSet rs, int n) throws SQLException {
    try {
      return new PaymentIntent(
          rs.getString("id"),
          rs.getLong("amount"),
          rs.getLong("amount_capturable"),
          rs.getLong("amount_received"),
          rs.getLong("amount_refunded"),
          rs.getString("currency"),
          rs.getString("capture_method"),
          PaymentStatus.fromWire(rs.getString("status")),
          rs.getLong("version"),
          mapper.readTree(rs.getString("metadata")),
          rs.getTimestamp("created_at").toInstant(),
          rs.getTimestamp("updated_at").toInstant());
    } catch (JsonProcessingException e) {
      throw new SQLException(e);
    }
  }

  private String json(JsonNode node) {
    try {
      return mapper.writeValueAsString(node);
    } catch (JsonProcessingException e) {
      throw new IllegalStateException(e);
    }
  }
}
