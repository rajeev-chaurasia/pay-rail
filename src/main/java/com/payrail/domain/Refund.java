package com.payrail.domain;

import java.time.Instant;

public record Refund(
    String id, String paymentIntentId, long amount, String status, Instant createdAt) {}
