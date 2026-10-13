package com.payrail.api;

import com.payrail.inspection.PaymentInspection;
import com.payrail.inspection.PaymentInspectionService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/payment_intents")
public class PaymentInspectionController {
  private final PaymentInspectionService inspections;

  public PaymentInspectionController(PaymentInspectionService inspections) {
    this.inspections = inspections;
  }

  @GetMapping("/{id}/inspect")
  public PaymentInspection inspect(@PathVariable String id) {
    return inspections.inspect(id);
  }
}
