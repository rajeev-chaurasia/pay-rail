package com.payrail.inspection;

import com.payrail.inspection.PaymentInspection.DeliveryEvent;
import com.payrail.inspection.PaymentInspection.LedgerEntry;
import com.payrail.inspection.PaymentInspection.LedgerJournal;
import com.payrail.inspection.PaymentInspection.ProviderOperation;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class PaymentInspectionRepository {
  private final JdbcTemplate jdbc;

  public PaymentInspectionRepository(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public PaymentInspection find(String tenant, String paymentId) {
    return new PaymentInspection(
        paymentId,
        journals(tenant, paymentId),
        events(tenant, paymentId),
        providerOperations(tenant, paymentId));
  }

  private List<LedgerJournal> journals(String tenant, String paymentId) {
    return jdbc.query(
        "select id,effect_key,currency,posted,created_at from ledger_transactions where tenant_id=? and payment_intent_id=? order by created_at,id",
        (rs, row) -> {
          List<LedgerEntry> entries = entries(rs.getString("id"));
          long debits = entries.stream().mapToLong(LedgerEntry::debit).sum();
          long credits = entries.stream().mapToLong(LedgerEntry::credit).sum();
          return new LedgerJournal(
              rs.getString("id"),
              rs.getString("effect_key"),
              rs.getString("currency"),
              rs.getBoolean("posted"),
              rs.getTimestamp("created_at").toInstant(),
              debits,
              credits,
              debits == credits && entries.size() >= 2,
              entries);
        },
        tenant,
        paymentId);
  }

  private List<LedgerEntry> entries(String journalId) {
    return jdbc.query(
        "select id,account,debit,credit,created_at from ledger_entries where ledger_transaction_id=? order by id",
        (rs, row) ->
            new LedgerEntry(
                rs.getLong("id"),
                rs.getString("account"),
                rs.getLong("debit"),
                rs.getLong("credit"),
                rs.getTimestamp("created_at").toInstant()),
        journalId);
  }

  private List<DeliveryEvent> events(String tenant, String paymentId) {
    return jdbc.query(
        "select id,event_type,aggregate_sequence,attempts,available_at,published_at,created_at from outbox_events where tenant_id=? and aggregate_type='payment_intent' and aggregate_id=? order by aggregate_sequence",
        (rs, row) ->
            new DeliveryEvent(
                rs.getString("id"),
                rs.getString("event_type"),
                rs.getLong("aggregate_sequence"),
                rs.getInt("attempts"),
                deliveryStatus(rs.getTimestamp("published_at"), rs.getTimestamp("available_at")),
                rs.getTimestamp("available_at").toInstant(),
                rs.getTimestamp("published_at") == null
                    ? null
                    : rs.getTimestamp("published_at").toInstant(),
                rs.getTimestamp("created_at").toInstant()),
        tenant,
        paymentId);
  }

  private List<ProviderOperation> providerOperations(String tenant, String paymentId) {
    return jdbc.query(
        "select provider_reference,status,created_at from simulated_provider_operations where stable_key=? order by created_at",
        (rs, row) ->
            new ProviderOperation(
                rs.getString("provider_reference"),
                rs.getString("status"),
                rs.getTimestamp("created_at").toInstant()),
        tenant + ":" + paymentId);
  }

  private String deliveryStatus(java.sql.Timestamp publishedAt, java.sql.Timestamp availableAt) {
    if (publishedAt != null) return "published";
    return availableAt.toInstant().isAfter(java.time.Instant.now()) ? "retry_scheduled" : "pending";
  }
}
