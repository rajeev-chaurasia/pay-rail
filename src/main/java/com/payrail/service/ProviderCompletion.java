package com.payrail.service;

public record ProviderCompletion(
    String consumer, String eventId, String tenantId, String paymentId, String providerReference) {}
