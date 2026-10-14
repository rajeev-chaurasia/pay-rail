package com.payrail.config;

import java.util.Arrays;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class ProductionSecretGuard implements SmartInitializingSingleton {
  private final Environment environment;
  private final PayRailProperties properties;
  private final JdbcTemplate jdbc;

  public ProductionSecretGuard(
      Environment environment, PayRailProperties properties, JdbcTemplate jdbc) {
    this.environment = environment;
    this.properties = properties;
    this.jdbc = jdbc;
  }

  @Override
  public void afterSingletonsInstantiated() {
    if (!Arrays.asList(environment.getActiveProfiles()).contains("prod")) return;
    require(
        properties.auth().pepper() != null
            && properties.auth().pepper().length() >= 32
            && !properties.auth().pepper().isBlank()
            && !properties.auth().pepper().contains("local-development"),
        "strong API_KEY_PEPPER");
    require(
        properties.migration().adminToken() != null
            && properties.migration().adminToken().length() >= 32
            && !properties.migration().adminToken().isBlank(),
        "strong MIGRATION_ADMIN_TOKEN");
    require(properties.rateLimit().enabled(), "enabled admission control");
    require(
        !environment.getProperty("spring.flyway.enabled", Boolean.class, true),
        "separate schema migration deployment");
    String[] parts = environment.getProperty("spring.datasource.url", "").split("\\?", 2);
    boolean verifiedTls =
        parts.length == 2
            && java.util.Arrays.stream(parts[1].split("&"))
                .filter(parameter -> parameter.startsWith("sslmode="))
                .toList()
                .equals(java.util.List.of("sslmode=verify-full"));
    require(verifiedTls, "verified PostgreSQL TLS");
    require(
        environment.getProperty("spring.data.redis.ssl.enabled", Boolean.class, false)
            && !environment.getProperty("spring.data.redis.password", "").isBlank(),
        "authenticated Redis TLS");
    require(
        java.util.Set.of("SSL", "SASL_SSL")
            .contains(environment.getProperty("spring.kafka.properties.security.protocol", "")),
        "Kafka TLS");
    Boolean privileged =
        jdbc.queryForObject(
            """
        select r.rolsuper or r.rolbypassrls or r.rolcreaterole or r.rolcreatedb
          or exists(select 1 from pg_class c where c.relnamespace='public'::regnamespace
            and c.relkind in ('r','p') and pg_has_role(current_user,c.relowner,'MEMBER'))
          or exists(select 1 from pg_roles elevated
            where pg_has_role(current_user,elevated.oid,'MEMBER')
              and (elevated.rolsuper or elevated.rolbypassrls or elevated.rolcreaterole
                or elevated.rolcreatedb or left(elevated.rolname,3)='pg_'))
          or has_schema_privilege(current_user,'public','CREATE')
        from pg_roles r where r.rolname=current_user
        """,
            Boolean.class);
    require(
        Boolean.FALSE.equals(privileged), "non-owner database role without elevated privileges");
  }

  private void require(boolean condition, String requirement) {
    if (!condition) throw new IllegalStateException("prod profile requires " + requirement);
  }
}
