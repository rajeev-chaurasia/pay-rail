package com.payrail.config;

import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import org.apache.kafka.clients.admin.NewTopic;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.FixedBackOff;

@Configuration
public class KafkaConfig {
  @Bean
  DeadLetterPublishingRecoverer providerDeadLetters(KafkaTemplate<String, String> kafka) {
    var recovery =
        new DeadLetterPublishingRecoverer(
            kafka,
            (record, error) ->
                new org.apache.kafka.common.TopicPartition(
                    "payrail.payment-events.DLT", record.partition()));
    recovery.setFailIfSendResultIsError(true);
    recovery.setWaitForSendResultTimeout(Duration.ofSeconds(10));
    recovery.setVerifyPartition(false);
    return recovery;
  }

  @Bean
  DefaultErrorHandler providerRetryHandler(
      DeadLetterPublishingRecoverer recovery, MeterRegistry registry) {
    var quarantined = registry.counter("payrail.provider.quarantine.publications");
    return new DefaultErrorHandler(
        (record, error) -> {
          recovery.accept(record, error);
          quarantined.increment();
        },
        new FixedBackOff(1000L, 5));
  }

  @Bean
  NewTopic providerQuarantineTopic() {
    return TopicBuilder.name("payrail.payment-events.DLT")
        .partitions(12)
        .replicas(1)
        .config("retention.ms", "604800000")
        .build();
  }
}
