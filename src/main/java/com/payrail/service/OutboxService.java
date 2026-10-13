package com.payrail.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.payrail.domain.PaymentIntent;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class OutboxService {
  private final JdbcTemplate jdbc;
  private final ObjectMapper mapper;

  public OutboxService(JdbcTemplate jdbc, ObjectMapper mapper) {
    this.jdbc = jdbc;
    this.mapper = mapper;
  }

  public void append(String tenant, PaymentIntent p, String type) {
    String eventId = UUID.randomUUID().toString();
    try {
      jdbc.update(
          "insert into outbox_events(id,tenant_id,aggregate_type,aggregate_id,aggregate_sequence,event_type,payload) values (?,?,?,?,?,?,?::jsonb)",
          eventId,
          tenant,
          "payment_intent",
          p.id(),
          p.version(),
          type,
          mapper.writeValueAsString(
              Map.of("event_id", eventId, "type", type, "tenant_id", tenant, "payment_intent", p)));
    } catch (JsonProcessingException e) {
      throw new IllegalStateException(e);
    }
  }
}
