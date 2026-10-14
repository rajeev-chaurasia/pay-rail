package com.payrail;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.payrail.config.PayRailProperties;
import com.payrail.config.ProductionSecretGuard;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;

class ProductionSecretGuardTest {
  private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
  private final MockEnvironment environment =
      new MockEnvironment()
          .withProperty("spring.flyway.enabled", "false")
          .withProperty("spring.datasource.url", "jdbc:postgresql://db/payrail?sslmode=verify-full")
          .withProperty("spring.data.redis.ssl.enabled", "true")
          .withProperty("spring.data.redis.password", "synthetic-test-secret")
          .withProperty("spring.kafka.properties.security.protocol", "SSL");
  private final PayRailProperties properties =
      new PayRailProperties(
          new PayRailProperties.Auth("synthetic-pepper-for-test-only-0123456789"),
          new PayRailProperties.RateLimit(true, 600),
          new PayRailProperties.Outbox(true, 100, 250),
          new PayRailProperties.Migration(true, 0, 0, "synthetic-admin-for-test-only-0123456789"));

  @Test
  void developmentProfilePreservesLocalDefaults() {
    new ProductionSecretGuard(environment, properties, jdbc).afterSingletonsInstantiated();
  }

  @Test
  void productionRejectsInsecureConfigurationAndElevatedRole() {
    environment.setActiveProfiles("prod");
    when(jdbc.queryForObject(anyString(), eq(Boolean.class))).thenReturn(false);
    var guard = new ProductionSecretGuard(environment, properties, jdbc);
    guard.afterSingletonsInstantiated();
    for (var invalid :
        java.util.Map.of(
                "spring.data.redis.ssl.enabled", "false",
                "spring.data.redis.password", "",
                "spring.kafka.properties.security.protocol", "PLAINTEXT")
            .entrySet()) {
      String previous = environment.getProperty(invalid.getKey());
      environment.setProperty(invalid.getKey(), invalid.getValue());
      assertThatThrownBy(() -> guard.afterSingletonsInstantiated())
          .isInstanceOf(IllegalStateException.class);
      environment.setProperty(invalid.getKey(), previous);
    }
    environment.setProperty("spring.flyway.enabled", "true");
    assertThatThrownBy(() -> guard.afterSingletonsInstantiated())
        .hasMessageContaining("separate schema migration");
    environment.setProperty("spring.flyway.enabled", "false");
    environment.setProperty(
        "spring.datasource.url", "jdbc:postgresql://db/payrail?ignored=sslmode=verify-full");
    assertThatThrownBy(() -> guard.afterSingletonsInstantiated())
        .hasMessageContaining("verified PostgreSQL TLS");
    environment.setProperty(
        "spring.datasource.url",
        "jdbc:postgresql://db/payrail?sslmode=verify-full&sslmode=disable");
    assertThatThrownBy(() -> guard.afterSingletonsInstantiated())
        .hasMessageContaining("verified PostgreSQL TLS");
    environment.setProperty("spring.datasource.url", "jdbc:postgresql://db/payrail");
    assertThatThrownBy(() -> guard.afterSingletonsInstantiated())
        .hasMessageContaining("verified PostgreSQL TLS");
    environment.setProperty(
        "spring.datasource.url", "jdbc:postgresql://db/payrail?sslmode=verify-full");
    when(jdbc.queryForObject(anyString(), eq(Boolean.class))).thenReturn(true);
    assertThatThrownBy(() -> guard.afterSingletonsInstantiated())
        .hasMessageContaining("non-owner database role");
  }
}
