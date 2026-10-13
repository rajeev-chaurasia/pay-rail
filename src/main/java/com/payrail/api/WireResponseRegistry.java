package com.payrail.api;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

@Component
public class WireResponseRegistry {
  private static final Set<String> SUPPORTED = Set.of("2025-01-01", "2026-01-01");
  private final ObjectMapper mapper;

  public WireResponseRegistry(ObjectMapper mapper) {
    this.mapper = mapper;
  }

  public void validate(String version) {
    if (!SUPPORTED.contains(version))
      throw new ApiException(
          HttpStatus.BAD_REQUEST,
          "unsupported_api_version",
          "Supported PayRail-Version values: " + SUPPORTED);
  }

  public String serialize(String version, Object value) {
    validate(version);
    try {
      var tree = mapper.valueToTree(value);
      if (version.equals("2025-01-01")) renameStatus(tree);
      return mapper.writeValueAsString(tree);
    } catch (JsonProcessingException e) {
      throw new IllegalStateException(e);
    }
  }

  private void renameStatus(com.fasterxml.jackson.databind.JsonNode node) {
    if (node instanceof ObjectNode object) {
      if (object.has("status")) object.set("state", object.remove("status"));
      object.elements().forEachRemaining(this::renameStatus);
    } else if (node.isArray()) node.forEach(this::renameStatus);
  }
}
