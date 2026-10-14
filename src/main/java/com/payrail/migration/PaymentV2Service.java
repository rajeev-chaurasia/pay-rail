package com.payrail.migration;

import com.payrail.config.PayRailProperties;
import com.payrail.domain.PaymentIntent;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentV2Service {
  private final JdbcTemplate jdbc;
  private final PayRailProperties.Migration config;
  private final com.fasterxml.jackson.databind.ObjectMapper mapper;

  public PaymentV2Service(
      JdbcTemplate jdbc, PayRailProperties p, com.fasterxml.jackson.databind.ObjectMapper mapper) {
    this.jdbc = jdbc;
    this.config = p.migration();
    this.mapper = mapper;
  }

  public void dualWrite(String tenant, PaymentIntent p) {
    if (config.dualWrite()) upsert(tenant, p);
  }

  private void upsert(String tenant, PaymentIntent p) {
    jdbc.update(
        "insert into payment_intents_v2(source_id,tenant_id,amount_minor,currency_code,capture_method,lifecycle_status,capturable_minor,captured_minor,refunded_minor,source_version,metadata,source_created_at,source_updated_at) values (?,?,?,?,?,?,?,?,?,?,?::jsonb,?,?) on conflict(source_id) do update set amount_minor=excluded.amount_minor,currency_code=excluded.currency_code,capture_method=excluded.capture_method,lifecycle_status=excluded.lifecycle_status,capturable_minor=excluded.capturable_minor,captured_minor=excluded.captured_minor,refunded_minor=excluded.refunded_minor,source_version=excluded.source_version,metadata=excluded.metadata,source_updated_at=excluded.source_updated_at,migrated_at=now() where payment_intents_v2.source_version<=excluded.source_version",
        p.id(),
        tenant,
        p.amount(),
        p.currency(),
        p.captureMethod(),
        p.status().wire(),
        p.amountCapturable(),
        p.amountReceived(),
        p.amountRefunded(),
        p.version(),
        p.metadata().toString(),
        java.sql.Timestamp.from(p.createdAt()),
        java.sql.Timestamp.from(p.updatedAt()));
  }

  @Transactional
  public int backfill(int size) {
    String last =
        jdbc.queryForObject(
            "select coalesce(last_key,'') from migration_checkpoints where migration_name='payment_intents_v2_backfill' for update",
            String.class);
    var batch =
        jdbc.queryForMap(
            """
        with chunk as materialized (
          select * from payment_intents where id>? order by id limit ?
        ), copied as (
          insert into payment_intents_v2(source_id,tenant_id,amount_minor,currency_code,
            capture_method,lifecycle_status,capturable_minor,captured_minor,refunded_minor,
            source_version,metadata,source_created_at,source_updated_at)
          select id,tenant_id,amount,currency,capture_method,status,amount_capturable,
            amount_received,amount_refunded,version,metadata,created_at,updated_at from chunk
          on conflict(source_id) do update set amount_minor=excluded.amount_minor,
            currency_code=excluded.currency_code,capture_method=excluded.capture_method,
            lifecycle_status=excluded.lifecycle_status,capturable_minor=excluded.capturable_minor,
            captured_minor=excluded.captured_minor,refunded_minor=excluded.refunded_minor,
            source_version=excluded.source_version,metadata=excluded.metadata,
            source_updated_at=excluded.source_updated_at,migrated_at=now()
          where payment_intents_v2.source_version<=excluded.source_version
          returning source_id
        ) select count(*) rows, max(id) last_key from chunk
        """,
            last,
            size);
    int count = ((Number) batch.get("rows")).intValue();
    if (count > 0)
      jdbc.update(
          "update migration_checkpoints set last_key=?,rows_processed=rows_processed+?,updated_at=now() where migration_name='payment_intents_v2_backfill'",
          batch.get("last_key"),
          count);
    return count;
  }

  public Map<String, Object> reconcile() {
    return jdbc.queryForMap(
        "select count(*) filter(where p.id is not null and v.source_id is null) missing, count(*) filter(where p.id is null and v.source_id is not null) extra, count(*) filter(where p.id is not null and v.source_id is not null and (p.tenant_id<>v.tenant_id or p.amount<>v.amount_minor or p.currency<>v.currency_code or p.capture_method<>v.capture_method or p.status<>v.lifecycle_status or p.amount_capturable<>v.capturable_minor or p.amount_received<>v.captured_minor or p.amount_refunded<>v.refunded_minor or p.version<>v.source_version or p.metadata<>v.metadata or p.created_at<>v.source_created_at or p.updated_at<>v.source_updated_at)) mismatched, count(p.id) source_total, count(v.source_id) target_total from payment_intents p full outer join payment_intents_v2 v on v.tenant_id=p.tenant_id and v.source_id=p.id");
  }

  public Map<String, Object> status() {
    return jdbc.queryForMap(
        "select last_key,rows_processed,cutover_ready,updated_at from migration_checkpoints where migration_name='payment_intents_v2_backfill'");
  }

  public Map<String, Object> gateCutover() {
    Map<String, Object> result = reconcile();
    boolean ready =
        config.dualWrite()
            && ((Number) result.get("missing")).longValue() == 0
            && ((Number) result.get("extra")).longValue() == 0
            && ((Number) result.get("mismatched")).longValue() == 0;
    jdbc.update(
        "update migration_checkpoints set cutover_ready=?,updated_at=now() where migration_name='payment_intents_v2_backfill'",
        ready);
    return new java.util.LinkedHashMap<>() {
      {
        putAll(result);
        put("cutover_ready", ready);
      }
    };
  }

  public PaymentIntent resolveRead(String tenant, PaymentIntent source) {
    int bucket = Math.floorMod((tenant + ":" + source.id()).hashCode(), 100);
    if (bucket >= config.shadowReadPercent() && bucket >= config.v2ReadPercent()) return source;
    var rows =
        jdbc.query(
            "select source_id,amount_minor,capturable_minor,captured_minor,refunded_minor,currency_code,capture_method,lifecycle_status,source_version,metadata::text,source_created_at,source_updated_at from payment_intents_v2 where tenant_id=? and source_id=?",
            (rs, n) -> {
              try {
                return new PaymentIntent(
                    rs.getString(1),
                    rs.getLong(2),
                    rs.getLong(3),
                    rs.getLong(4),
                    rs.getLong(5),
                    rs.getString(6),
                    rs.getString(7),
                    com.payrail.domain.PaymentStatus.fromWire(rs.getString(8)),
                    rs.getLong(9),
                    mapper.readTree(rs.getString(10)),
                    rs.getTimestamp(11).toInstant(),
                    rs.getTimestamp(12).toInstant());
              } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
                throw new java.sql.SQLException(e);
              }
            },
            tenant,
            source.id());
    if (rows.isEmpty()) return source;
    PaymentIntent target = rows.get(0);
    boolean equivalent = source.equals(target);
    if (!equivalent)
      org.slf4j.LoggerFactory.getLogger(PaymentV2Service.class)
          .warn(
              "payment v2 shadow mismatch tenant={} id={} sourceVersion={} targetVersion={}",
              tenant,
              source.id(),
              source.version(),
              target.version());
    Boolean ready =
        jdbc.queryForObject(
            "select cutover_ready from migration_checkpoints where migration_name='payment_intents_v2_backfill'",
            Boolean.class);
    return equivalent && bucket < config.v2ReadPercent() && Boolean.TRUE.equals(ready)
        ? target
        : source;
  }
}
