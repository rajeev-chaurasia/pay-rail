package com.payrail.outbox;

import com.payrail.config.PayRailProperties;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.internals.RecordHeader;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OutboxDispatcher {
  private final OutboxRepository repository;
  private final KafkaTemplate<String, String> kafka;
  private final PayRailProperties.Outbox config;

  public OutboxDispatcher(
      OutboxRepository repository, KafkaTemplate<String, String> kafka, PayRailProperties p) {
    this.repository = repository;
    this.kafka = kafka;
    this.config = p.outbox();
  }

  @Scheduled(fixedDelayString = "${payrail.outbox.fixed-delay-ms:250}")
  public void dispatch() {
    if (!config.enabled()) return;
    for (int i = 0; i < config.batchSize(); i++) {
      var claimed = repository.claim(1);
      if (claimed.isEmpty()) break;
      var e = claimed.get(0);
      try {
        ProducerRecord<String, String> record =
            new ProducerRecord<>("payrail.payment-events", e.aggregateId(), e.payload());
        record.headers().add(new RecordHeader("event-id", e.id().getBytes(StandardCharsets.UTF_8)));
        record
            .headers()
            .add(
                new RecordHeader(
                    "aggregate-sequence",
                    Long.toString(e.sequence()).getBytes(StandardCharsets.UTF_8)));
        kafka.send(record).get(20, TimeUnit.SECONDS);
        repository.published(e.id(), e.leaseToken());
      } catch (Exception ex) {
        repository.failed(e.id(), e.leaseToken(), ex.toString());
      }
    }
  }
}
