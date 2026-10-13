package com.payrail.service;

import com.fasterxml.jackson.databind.JsonNode;

public record CreatePaymentCommand(
    long amount, String currency, String captureMethod, JsonNode metadata) {}
