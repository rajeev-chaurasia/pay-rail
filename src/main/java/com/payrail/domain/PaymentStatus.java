package com.payrail.domain;

import java.util.Set;

public enum PaymentStatus {
  REQUIRES_CONFIRMATION,
  PROCESSING,
  AUTHORIZED,
  SUCCEEDED,
  FAILED,
  PARTIALLY_REFUNDED,
  REFUNDED,
  CANCELED;

  @com.fasterxml.jackson.annotation.JsonValue
  public String wire() {
    return name().toLowerCase();
  }

  public boolean canTransitionTo(PaymentStatus next) {
    return switch (this) {
      case REQUIRES_CONFIRMATION -> Set.of(PROCESSING, AUTHORIZED, CANCELED).contains(next);
      case PROCESSING -> Set.of(SUCCEEDED, FAILED).contains(next);
      case AUTHORIZED -> Set.of(SUCCEEDED, CANCELED).contains(next);
      case SUCCEEDED -> Set.of(PARTIALLY_REFUNDED, REFUNDED).contains(next);
      case PARTIALLY_REFUNDED -> Set.of(PARTIALLY_REFUNDED, REFUNDED).contains(next);
      case REFUNDED, CANCELED, FAILED -> false;
    };
  }

  public static PaymentStatus fromWire(String value) {
    return valueOf(value.toUpperCase());
  }
}
