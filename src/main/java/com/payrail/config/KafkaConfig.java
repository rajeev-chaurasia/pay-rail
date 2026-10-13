package com.payrail.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.FixedBackOff;

@Configuration
public class KafkaConfig {
  @Bean
  DefaultErrorHandler providerRetryHandler() {
    return new DefaultErrorHandler(new FixedBackOff(1_000L, Long.MAX_VALUE));
  }
}
