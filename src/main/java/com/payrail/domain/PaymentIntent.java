package com.payrail.domain;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;

public record PaymentIntent(
    String id,
    long amount,
    long amountCapturable,
    long amountReceived,
    long amountRefunded,
    String currency,
    String captureMethod,
    PaymentStatus status,
    long version,
    JsonNode metadata,
    Instant createdAt,
    Instant updatedAt) {}
