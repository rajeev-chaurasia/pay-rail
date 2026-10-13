package com.payrail.inspection;

import java.time.Instant;
import java.util.List;

public record PaymentInspection(
    String paymentIntentId,
    List<LedgerJournal> journals,
    List<DeliveryEvent> events,
    List<ProviderOperation> providerOperations) {

  public record LedgerJournal(
      String id,
      String effectKey,
      String currency,
      boolean posted,
      Instant createdAt,
      long debitTotal,
      long creditTotal,
      boolean balanced,
      List<LedgerEntry> entries) {}

  public record LedgerEntry(long id, String account, long debit, long credit, Instant createdAt) {}

  public record DeliveryEvent(
      String id,
      String type,
      long sequence,
      int attempts,
      String deliveryStatus,
      Instant availableAt,
      Instant publishedAt,
      Instant createdAt) {}

  public record ProviderOperation(String reference, String outcome, Instant createdAt) {}
}
