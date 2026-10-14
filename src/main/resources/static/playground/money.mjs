export function formatMoney(minorUnits, currency = "usd") {
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  });
  const exponent = formatter.resolvedOptions().maximumFractionDigits;
  return formatter.format(minorUnits / 10 ** exponent);
}
