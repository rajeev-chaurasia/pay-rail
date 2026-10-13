package com.payrail.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.payrail.api.ApiException;
import com.payrail.api.WireResponseRegistry;
import com.payrail.auth.TenantContext;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.function.Supplier;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class IdempotencyService {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate transactions;
  private final ObjectMapper mapper;
  private final WireResponseRegistry wire;

  public IdempotencyService(
      JdbcTemplate jdbc,
      TransactionTemplate transactions,
      ObjectMapper mapper,
      WireResponseRegistry wire) {
    this.jdbc = jdbc;
    this.transactions = transactions;
    this.mapper = mapper;
    this.wire = wire;
  }

  public record PinnedResponse(int status, String apiVersion, String body) {}

  public record RawCommand(
      String key,
      String operation,
      String apiVersion,
      Object request,
      int responseStatus,
      Supplier<?> action) {}

  public record TypedCommand<T>(RawCommand raw, Class<T> responseType) {}

  private record StoredResponse(
      String operation,
      String fingerprint,
      Integer status,
      String body,
      String apiVersion,
      boolean completed) {}

  public PinnedResponse executeRaw(RawCommand command) {
    validate(command);
    String tenant = TenantContext.require();
    String fingerprint = fingerprint(command, command.request());
    return transactions.execute(ignored -> executeLocked(command, tenant, fingerprint));
  }

  public <T> T execute(TypedCommand<T> command) {
    PinnedResponse response = executeRaw(command.raw());
    try {
      return mapper.readValue(response.body(), command.responseType());
    } catch (JsonProcessingException e) {
      throw new IllegalStateException("stored response is invalid", e);
    }
  }

  private PinnedResponse executeLocked(RawCommand command, String tenant, String fingerprint) {
    reserve(command, tenant, fingerprint);
    StoredResponse stored = findForUpdate(tenant, command.key());
    rejectConflictingReuse(command, fingerprint, stored);
    if (stored.completed()) return replay(stored);
    String body = wire.serialize(command.apiVersion(), command.action().get());
    saveResponse(command, tenant, body);
    return new PinnedResponse(command.responseStatus(), command.apiVersion(), body);
  }

  private void reserve(RawCommand command, String tenant, String fingerprint) {
    jdbc.update(
        "insert into idempotency_records(tenant_id,idempotency_key,operation,request_fingerprint,api_version) values (?,?,?,?,?) on conflict (tenant_id,idempotency_key) do nothing",
        tenant,
        command.key(),
        command.operation(),
        fingerprint,
        command.apiVersion());
  }

  private StoredResponse findForUpdate(String tenant, String key) {
    return jdbc.queryForObject(
        "select operation,request_fingerprint,response_status,response_body,api_version,completed from idempotency_records where tenant_id=? and idempotency_key=? for update",
        (rs, row) ->
            new StoredResponse(
                rs.getString(1),
                rs.getString(2),
                (Integer) rs.getObject(3),
                rs.getString(4),
                rs.getString(5),
                rs.getBoolean(6)),
        tenant,
        key);
  }

  private void rejectConflictingReuse(
      RawCommand command, String fingerprint, StoredResponse stored) {
    if (command.operation().equals(stored.operation())
        && fingerprint.equals(stored.fingerprint())) {
      return;
    }
    throw new ApiException(
        HttpStatus.CONFLICT,
        "idempotency_conflict",
        "Idempotency key was already used with a different request");
  }

  private void saveResponse(RawCommand command, String tenant, String body) {
    jdbc.update(
        "update idempotency_records set response_status=?,response_headers=jsonb_build_object('PayRail-Version',?),response_body=?,completed=true where tenant_id=? and idempotency_key=?",
        command.responseStatus(),
        command.apiVersion(),
        body,
        tenant,
        command.key());
  }

  private PinnedResponse replay(StoredResponse stored) {
    return new PinnedResponse(stored.status(), stored.apiVersion(), stored.body());
  }

  private void validate(RawCommand command) {
    wire.validate(command.apiVersion());
    String key = command.key();
    if (key == null || key.isBlank() || key.length() > 255) {
      throw new ApiException(
          HttpStatus.BAD_REQUEST,
          "invalid_idempotency_key",
          "Idempotency-Key must be 1..255 characters");
    }
  }

  private String fingerprint(RawCommand command, Object request) {
    String operation = command.operation() + "\napi-version:" + command.apiVersion();
    try {
      JsonNode canonical = canonicalize(mapper.valueToTree(request));
      byte[] bytes =
          ("sha256-v1\n" + operation + "\n" + mapper.writeValueAsString(canonical))
              .getBytes(StandardCharsets.UTF_8);
      return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    } catch (NoSuchAlgorithmException | JsonProcessingException e) {
      throw new IllegalStateException(e);
    }
  }

  private JsonNode canonicalize(JsonNode node) {
    if (node.isObject()) {
      var sorted = mapper.createObjectNode();
      java.util.List<String> names = new java.util.ArrayList<>();
      node.fieldNames().forEachRemaining(names::add);
      java.util.Collections.sort(names);
      for (String name : names) sorted.set(name, canonicalize(node.get(name)));
      return sorted;
    }
    if (node.isArray()) {
      var result = mapper.createArrayNode();
      node.forEach(n -> result.add(canonicalize(n)));
      return result;
    }
    return node;
  }
}
