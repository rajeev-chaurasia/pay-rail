package com.payrail;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.payrail.config.PayRailProperties;
import com.payrail.outbox.OutboxDispatcher;
import com.payrail.outbox.OutboxRepository;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

class OutboxDispatcherTest {
  @Test
  @SuppressWarnings("unchecked")
  void submitsIndependentHeadsBeforeWaitingAndRetriesFailedDelivery() {
    var repository = mock(OutboxRepository.class);
    KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
    var first = new OutboxRepository.Event("first", "payment-a", 1, "created", "{}", "lease-a");
    var second = new OutboxRepository.Event("second", "payment-b", 1, "created", "{}", "lease-b");
    when(repository.claim(100)).thenReturn(List.of(first, second));
    var acknowledgement = new CompletableFuture<SendResult<String, String>>();
    when(kafka.send(any(org.apache.kafka.clients.producer.ProducerRecord.class)))
        .thenReturn(acknowledgement)
        .thenAnswer(
            call -> {
              acknowledgement.complete(null);
              return CompletableFuture.failedFuture(
                  new IllegalStateException("synthetic broker failure"));
            });
    var properties =
        new PayRailProperties(null, null, new PayRailProperties.Outbox(true, 100, 250), null);
    new OutboxDispatcher(repository, kafka, properties).dispatch();
    verify(repository).published("first", "lease-a");
    verify(repository).failed(eq("second"), eq("lease-b"), contains("synthetic broker failure"));
    verify(repository, never()).published("second", "lease-b");
  }
}
