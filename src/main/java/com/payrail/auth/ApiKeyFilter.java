package com.payrail.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Map;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class ApiKeyFilter extends OncePerRequestFilter {
  private final JdbcTemplate jdbc;
  private final ApiKeyHasher hasher;
  private final RateLimiter rateLimiter;
  private final ObjectMapper objectMapper;

  public ApiKeyFilter(
      JdbcTemplate jdbc, ApiKeyHasher hasher, RateLimiter rateLimiter, ObjectMapper objectMapper) {
    this.jdbc = jdbc;
    this.hasher = hasher;
    this.rateLimiter = rateLimiter;
    this.objectMapper = objectMapper;
  }

  @Override
  protected boolean shouldNotFilter(HttpServletRequest request) {
    String p = request.getRequestURI();
    return !p.startsWith("/v1/") || p.startsWith("/v1/admin/");
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String key = request.getHeader("Authorization");
    if (key == null || !key.startsWith("Bearer ")) {
      unauthorized(response);
      return;
    }
    var tenants =
        jdbc.query(
            "select tenant_id from api_keys where key_hash=? and enabled",
            (rs, n) -> rs.getString(1),
            hasher.hash(key.substring(7)));
    if (tenants.isEmpty()) {
      unauthorized(response);
      return;
    }
    try {
      TenantContext.set(tenants.get(0));
      rateLimiter.check(tenants.get(0));
      chain.doFilter(request, response);
    } catch (com.payrail.api.ApiException e) {
      response.setStatus(e.status().value());
      response.setContentType("application/json");
      if (e.status().value() == 429) response.setHeader("Retry-After", "60");
      objectMapper.writeValue(
          response.getOutputStream(),
          Map.of("error", Map.of("code", e.code(), "message", e.getMessage())));
    } finally {
      TenantContext.clear();
    }
  }

  private void unauthorized(HttpServletResponse response) throws IOException {
    response.setStatus(401);
    response.setContentType("application/json");
    objectMapper.writeValue(
        response.getOutputStream(),
        Map.of(
            "error",
            Map.of("code", "invalid_api_key", "message", "A valid Bearer API key is required")));
  }
}
