package com.payrail.inspection;

import com.payrail.auth.TenantContext;
import com.payrail.service.PaymentService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentInspectionService {
  private final PaymentService payments;
  private final PaymentInspectionRepository inspections;

  public PaymentInspectionService(
      PaymentService payments, PaymentInspectionRepository inspections) {
    this.payments = payments;
    this.inspections = inspections;
  }

  @Transactional(readOnly = true)
  public PaymentInspection inspect(String paymentId) {
    payments.get(paymentId);
    return inspections.find(TenantContext.require(), paymentId);
  }
}
