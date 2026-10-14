import test from "node:test";
import assert from "node:assert/strict";
import { formatMoney } from "../../src/main/resources/static/playground/money.mjs";

test("supported currencies use their minor-unit exponent", () => {
  assert.equal(formatMoney(2500, "usd"), "$25.00");
  assert.equal(formatMoney(2500, "eur"), "€25.00");
  assert.equal(formatMoney(2500, "gbp"), "£25.00");
  assert.equal(formatMoney(1000, "jpy"), "¥1,000");
  assert.equal(formatMoney(0, "jpy"), "¥0");
  assert.equal(formatMoney(-100, "usd"), "-$1.00");
  assert.match(formatMoney(2500, "cad"), /25\.00$/);
  assert.match(formatMoney(2500, "aud"), /25\.00$/);
});
