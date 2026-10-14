package com.payrail.config;

import java.util.Arrays;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class ProductionSecretGuard implements ApplicationRunner {
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
  public void run(ApplicationArguments args) {
    if (!Arrays.asList(environment.getActiveProfiles()).contains("prod")) return;
    require(
        properties.auth().pepper() != null
            && properties.auth().pepper().length() >= 32
            && !properties.auth().pepper().contains("local-development"),
        "strong API_KEY_PEPPER");
    require(
        properties.migration().adminToken() != null
            && properties.migration().adminToken().length() >= 32,
        "strong MIGRATION_ADMIN_TOKEN");
    require(properties.rateLimit().enabled(), "enabled admission control");
    require(
        !environment.getProperty("spring.flyway.enabled", Boolean.class, true),
        "separate schema migration deployment");
    require(
        environment
            .getProperty("spring.datasource.url", "")
            .matches(".*[?&]sslmode=verify-full(?:&[^#]*)?$"),
        "verified PostgreSQL TLS");
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
