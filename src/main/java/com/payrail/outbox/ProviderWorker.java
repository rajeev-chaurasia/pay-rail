package com.payrail.outbox;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.payrail.service.PaymentService;
import com.payrail.service.ProviderCompletion;
import com.payrail.service.SimulatedProvider;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

@Component
public class ProviderWorker {
  private final ObjectMapper mapper;
  private final SimulatedProvider provider;
  private final PaymentService payments;

  public ProviderWorker(ObjectMapper mapper, SimulatedProvider provider, PaymentService payments) {
    this.mapper = mapper;
    this.provider = provider;
    this.payments = payments;
  }

  @KafkaListener(topics = "payrail.payment-events")
  public void onEvent(
      String payload, @Header(name = "event-id", required = false) byte[] eventHeader)
      throws Exception {
    JsonNode root = mapper.readTree(payload);
    if (!"provider.authorization.requested".equals(root.path("type").asText())) return;
    String eventId =
        eventHeader == null
            ? root.path("event_id").asText()
            : new String(eventHeader, java.nio.charset.StandardCharsets.UTF_8);
    String tenant = root.path("tenant_id").asText();
    String intent = root.path("payment_intent").path("id").asText();
    String reference = provider.authorize(tenant + ":" + intent);
    payments.completeProvider(
        new ProviderCompletion("simulated-provider", eventId, tenant, intent, reference));
  }
}
