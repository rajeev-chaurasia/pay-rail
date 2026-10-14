package com.payrail.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.util.concurrent.CompletableFuture;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.TopicPartition;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

class KafkaRecoveryTest {
  @Test
  @SuppressWarnings("unchecked")
  void recoveryRequiresSuccessfulPublicationAndPreservesRecord() {
    KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
    when(kafka.send(any(ProducerRecord.class)))
        .thenAnswer(
            call -> {
              ProducerRecord<String, String> record = call.getArgument(0);
              return CompletableFuture.completedFuture(
                  new SendResult<>(
                      record,
                      new RecordMetadata(new TopicPartition(record.topic(), 0), 7, 0, 0, 0, 0)));
            });
    var recovery = new KafkaConfig().providerDeadLetters(kafka);
    recovery.accept(
        new ConsumerRecord<>("payrail.payment-events", 0, 7, "synthetic-key", "synthetic-payload"),
        new IllegalArgumentException("synthetic failure"));
    ArgumentCaptor<ProducerRecord> records = ArgumentCaptor.forClass(ProducerRecord.class);
    verify(kafka).send(records.capture());
    assertThat(records.getValue().topic()).isEqualTo("payrail.payment-events.DLT");
    assertThat(records.getValue().key()).isEqualTo("synthetic-key");
    assertThat(records.getValue().value()).isEqualTo("synthetic-payload");
  }

  @Test
  @SuppressWarnings("unchecked")
  void failedQuarantinePublicationCannotResolveRecovery() {
    KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
    when(kafka.send(any(ProducerRecord.class)))
        .thenReturn(
            CompletableFuture.failedFuture(
                new IllegalStateException("synthetic broker unavailable")));
    var recovery = new KafkaConfig().providerDeadLetters(kafka);
    assertThatThrownBy(
            () ->
                recovery.accept(
                    new ConsumerRecord<>(
                        "payrail.payment-events", 0, 7, "synthetic-key", "synthetic-payload"),
                    new IllegalArgumentException("synthetic failure")))
        .isInstanceOf(org.springframework.kafka.KafkaException.class);
  }
}
