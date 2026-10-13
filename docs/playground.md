# Live playground

Start the stack with `./scripts/dev-up.sh` and open `http://localhost:18080/`.
The UI is served by Spring Boot from the same origin as the API. There is no
frontend runtime dependency, separate server or cross-origin credential proxy.

## Five-minute walkthrough

1. Create an automatic USD intent for 2500 minor units. The response is HTTP
   201 with `requires_confirmation`. The delivery timeline shows the stored
   creation event and updates as it is acknowledged by Kafka.
2. Send eight concurrent retries. Compare all responses with the original
   bytes. Change the amount under the same key to observe a fingerprint 409.
   These are replays of a stored request, not a benchmark of initial contention.
3. Confirm. The response is HTTP 202 with `processing`. The page polls for
   provider completion and event delivery for up to 30 seconds. Use Refresh
   if work remains pending. The inspection shows a balanced capture journal.
4. Refund 500 minor units. The amount refunded becomes 500 and a separate
   reversing journal appears. Replay that refund without creating another
   effect. The original capture journal remains intact.
5. Compare both API contracts. The older response uses `state`, the current
   response uses `status`. If the version changes between reads, compare again
   after processing settles. Comparisons clear when the selected payment changes.
6. Generate a new key and select manual capture. Confirm authorizes the
   amount; Capture posts it. Alternatively cancel before capture.

The recent-payment selector loads the latest 20 tenant payments. Every action
shows its method, path, key, selected contract, measured browser request time
and real response. The displayed time is a local observation, not throughput.

## Migration controls

The Migration lab requires the configured admin token entered explicitly.
The synthetic local default is `local-admin-token`. Production must supply a
different credential. Admin operations cover all tenants in this database.
Inspect status, backfill a batch, reconcile, then check cutover readiness.
The gate does not change deployment environment percentages.

## Boundaries and recovery

API credentials remain in page memory and password fields; they are not saved
in local storage, URLs, request inspection or logs. Changing tenant credentials
clears previous observations. Requests are same-origin and dynamic output uses
text nodes, preventing response content from becoming executable markup.

Before sending a mutation the browser retains its key, body and contract. An
unknown transport outcome locks new mutations until a replay recovers the
saved response. This protection lasts only while the page remains open. Copy
and retain the displayed idempotency key before closing the page if an outcome
is uncertain; use the API to recover it afterward.

`GET /v1/payment_intents/{id}/inspect` authenticates the tenant and checks payment
ownership. It returns journal entries and totals, event IDs/types/delivery
metadata, and simulated provider outcomes. Raw event payloads, stable provider
keys, lease tokens and errors are omitted. Other-tenant IDs return 404.
Inspection queries can observe successive committed database snapshots; the
screen is an observational view, not an atomic accounting statement.

The interface labels payments as simulated. It does not show fabricated
performance metrics, reset production data or move real funds. Keyboard focus,
explicit labels and responsive layouts were checked locally; a full accessibility
audit has not been performed.
