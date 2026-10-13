package com.payrail.config;

import java.util.Arrays;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class ProductionSecretGuard implements ApplicationRunner {
  private final Environment environment;
  private final PayRailProperties properties;

  public ProductionSecretGuard(Environment environment, PayRailProperties properties) {
    this.environment = environment;
    this.properties = properties;
  }

  @Override
  public void run(ApplicationArguments args) {
    if (Arrays.asList(environment.getActiveProfiles()).contains("prod")
        && (properties.auth().pepper().contains("local-development")
            || properties.migration().adminToken().equals("local-admin-token")))
      throw new IllegalStateException(
          "prod profile requires non-default API_KEY_PEPPER and MIGRATION_ADMIN_TOKEN");
  }
}
