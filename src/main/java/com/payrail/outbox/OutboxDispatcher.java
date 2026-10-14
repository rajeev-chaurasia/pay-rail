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
    var claimed = repository.claim(config.batchSize());
    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
    var pending = new java.util.ArrayList<Delivery>();
    for (var event : claimed) {
      if (System.nanoTime() >= deadline) break;
      pending.add(send(event));
    }
    for (var delivery : pending) {
      var event = delivery.event();
      try {
        delivery.result().get(Math.max(1, deadline - System.nanoTime()), TimeUnit.NANOSECONDS);
        repository.published(event.id(), event.leaseToken());
      } catch (InterruptedException ex) {
        Thread.currentThread().interrupt();
        return; // Remaining leases expire and recover without acknowledging an uncertain send.
      } catch (Exception ex) {
        repository.failed(event.id(), event.leaseToken(), ex.toString());
      }
    }
  }

  private Delivery send(OutboxRepository.Event event) {
    try {
      ProducerRecord<String, String> record =
          new ProducerRecord<>("payrail.payment-events", event.aggregateId(), event.payload());
      record
          .headers()
          .add(new RecordHeader("event-id", event.id().getBytes(StandardCharsets.UTF_8)));
      record
          .headers()
          .add(
              new RecordHeader(
                  "aggregate-sequence",
                  Long.toString(event.sequence()).getBytes(StandardCharsets.UTF_8)));
      return new Delivery(event, kafka.send(record));
    } catch (Exception ex) {
      return new Delivery(event, java.util.concurrent.CompletableFuture.failedFuture(ex));
    }
  }

  private record Delivery(
      OutboxRepository.Event event, java.util.concurrent.CompletableFuture<?> result) {}
}
