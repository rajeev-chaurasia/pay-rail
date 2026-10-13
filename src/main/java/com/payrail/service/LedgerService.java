package com.payrail.service;

import com.payrail.domain.PaymentIntent;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class LedgerService {
  private final JdbcTemplate jdbc;

  public LedgerService(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public void postCapture(String tenant, PaymentIntent p, long amount) {
    post(tenant, p, "capture:" + p.id(), "provider_clearing", "merchant_payable", amount);
  }

  public void postRefund(String tenant, PaymentIntent p, String refundId, long amount) {
    post(tenant, p, "refund:" + refundId, "merchant_payable", "provider_clearing", amount);
  }

  private void post(
      String tenant,
      PaymentIntent p,
      String effect,
      String debitAccount,
      String creditAccount,
      long amount) {
    String tx = "ltx_" + UUID.randomUUID().toString().replace("-", "");
    int created =
        jdbc.update(
            "insert into ledger_transactions(id,tenant_id,payment_intent_id,effect_key,currency) values (?,?,?,?,?) on conflict (tenant_id,effect_key) do nothing",
            tx,
            tenant,
            p.id(),
            effect,
            p.currency());
    if (created == 0) return;
    jdbc.update(
        "insert into ledger_entries(ledger_transaction_id,account,debit,credit) values (?,?,?,0)",
        tx,
        debitAccount,
        amount);
    jdbc.update(
        "insert into ledger_entries(ledger_transaction_id,account,debit,credit) values (?,?,0,?)",
        tx,
        creditAccount,
        amount);
    jdbc.update("update ledger_transactions set posted=true where id=? and posted=false", tx);
  }
}
