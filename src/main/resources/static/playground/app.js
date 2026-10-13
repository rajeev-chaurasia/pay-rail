const $ = (id) => document.getElementById(id);
const state = {
  payment: null,
  inspection: null,
  lastMutation: null,
  busy: false,
  generation: 0,
  pollGeneration: 0,
  credential: "pr_test_demo",
};
const money = (value, currency = "usd") =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(value / 100);
const key = () => `demo_${crypto.randomUUID()}`;
const pretty = (value) => JSON.stringify(value, null, 2);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function notify(message, error = false, target = "notice") {
  const node = $(target);
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = false;
}

function inspectRequest(result) {
  $("request-status").textContent = `HTTP ${result.status}`;
  $("request-path").textContent = `${result.method} ${result.path}`;
  $("request-body").textContent = pretty({
    method: result.method,
    path: result.path,
    apiVersion: result.version,
    ...(result.key ? { idempotencyKey: result.key } : {}),
    ...(result.body !== undefined ? { body: result.body } : {}),
  });
  $("response-time").textContent = `${Math.round(result.duration)} ms`;
  $("response-body").textContent = result.data
    ? pretty(result.data)
    : result.text;
}

async function api(path, options = {}) {
  const generation = state.generation;
  const version = options.version || $("api-version").value;
  const headers = {
    "Content-Type": "application/json",
    "PayRail-Version": version,
  };
  if (options.admin) {
    if (!$("admin-token").value.trim())
      throw new Error("Enter the configured migration admin token first.");
    headers["X-Admin-Token"] = $("admin-token").value;
  } else headers.Authorization = `Bearer ${state.credential}`;
  if (options.key) headers["Idempotency-Key"] = options.key;
  const started = performance.now();
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: AbortSignal.timeout(15000),
    cache: "no-store",
  });
  const text = await response.text();
  if (generation !== state.generation)
    throw new Error("Connection changed; stale response ignored.");
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = null;
  }
  const result = {
    status: response.status,
    ok: response.ok,
    method: options.method || "GET",
    path,
    version,
    key: options.key,
    body: options.body,
    text,
    data,
    duration: performance.now() - started,
  };
  if (options.show !== false) inspectRequest(result);
  return result;
}

function requireSuccess(result) {
  if (!result.ok)
    throw new Error(
      `HTTP ${result.status}: ${result.data?.error?.message || result.text || "Request failed"}`,
    );
  return result;
}

async function run(action) {
  if (state.busy) return;
  state.pollGeneration++;
  state.busy = true;
  syncButtons();
  try {
    await action();
  } catch (error) {
    notify(
      state.lastMutation && state.lastMutation.response === undefined
        ? `${error.message} The outcome is uncertain. Replay the saved key before starting another mutation.`
        : error.message,
      true,
    );
  } finally {
    state.busy = false;
    syncButtons();
  }
}

function syncButtons() {
  const payment = state.payment;
  const status = payment?.status || payment?.state;
  for (const node of document.querySelectorAll("button")) {
    if (!node.classList.contains("nav")) node.disabled = state.busy;
  }
  for (const id of ["api-key", "api-version", "recent"])
    $(id).disabled = state.busy;
  $("confirm").hidden = status !== "requires_confirmation";
  $("capture-payment").hidden = status !== "authorized";
  $("cancel").hidden = !["requires_confirmation", "authorized"].includes(
    status,
  );
  $("refund-group").hidden = !["succeeded", "partially_refunded"].includes(
    status,
  );
  for (const id of ["retry", "race"])
    $(id).disabled = state.busy || !state.lastMutation;
  $("conflict").disabled =
    state.busy || state.lastMutation?.path !== "/v1/payment_intents";
  $("compare").disabled = state.busy || !payment;
  $("refresh").disabled = state.busy || !payment;
  const uncertain =
    state.lastMutation && state.lastMutation.response === undefined;
  if (uncertain) {
    for (const id of ["api-key", "api-version", "recent"])
      $(id).disabled = true;
    for (const id of ["confirm", "capture-payment", "cancel", "refund"])
      $(id).disabled = true;
    $("create-form").querySelector("[type=submit]").disabled = true;
  }
}

function renderPayment(payment) {
  if (
    state.payment?.id !== payment.id ||
    state.payment?.version !== payment.version
  ) {
    $("old-contract").textContent =
      "Compare the selected payment at its current version.";
    $("new-contract").textContent =
      "Compare the selected payment at its current version.";
  }
  state.payment = payment;
  const status = payment.status || payment.state;
  $("empty-intent").hidden = true;
  $("intent-content").hidden = false;
  $("copy-id").textContent = `${payment.id} ⧉`;
  $("payment-status").textContent = status;
  $("payment-status").classList.toggle(
    "failed",
    status === "failed" || status === "canceled",
  );
  $("payment-amount").textContent = money(payment.amount, payment.currency);
  $("payment-currency").textContent = payment.currency.toUpperCase();
  $("payment-mode").textContent =
    `${payment.captureMethod} capture · v${payment.version}`;
  $("received").textContent = money(payment.amountReceived, payment.currency);
  $("capturable").textContent = money(
    payment.amountCapturable,
    payment.currency,
  );
  $("refunded").textContent = money(payment.amountRefunded, payment.currency);
  $("refund-amount").max = payment.amountReceived - payment.amountRefunded;
  const steps =
    payment.captureMethod === "manual"
      ? ["Created", "Authorized", "Captured", "Refunded"]
      : ["Created", "Processing", "Captured", "Refunded"];
  const index =
    {
      requires_confirmation: 0,
      processing: 1,
      authorized: 1,
      succeeded: 2,
      partially_refunded: 3,
      refunded: 3,
      canceled: 0,
      failed: 1,
    }[status] ?? 0;
  $("lifecycle").replaceChildren(
    ...steps.map((name, position) => {
      const step = document.createElement("div");
      step.className = `life-step ${position === index ? "current" : position < index ? "done" : ""}`;
      step.append(document.createElement("i"), document.createTextNode(name));
      return step;
    }),
  );
  const hints = {
    requires_confirmation:
      "Confirm to begin provider processing. Manual capture authorizes the amount first.",
    processing:
      "The provider worker is running. This page polls for completion for up to 30 seconds.",
    authorized:
      "Capture the full authorized amount, or cancel before funds are captured.",
    succeeded:
      "Funds are captured in the simulation. Inspect the balanced journal or issue a refund.",
    partially_refunded:
      "A partial refund creates a separate reversing journal. The original posting remains immutable.",
    refunded:
      "The captured amount has been fully refunded. Historical journal entries remain intact.",
    canceled: "This intent is canceled. It has no capture posting.",
    failed:
      "Provider processing failed. Inspect the persisted delivery events.",
  };
  $("state-help").textContent = hints[status] || status;
  syncButtons();
}

function cell(text, tag = "td") {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function renderInspection(inspection) {
  state.inspection = inspection;
  const journals = inspection.journals || [];
  $("ledger-empty").hidden = journals.length > 0;
  $("ledger-table").hidden = journals.length === 0;
  $("ledger-rows").replaceChildren();
  let debit = 0,
    credit = 0;
  for (const journal of journals) {
    for (const entry of journal.entries) {
      const row = document.createElement("tr");
      const account = cell(entry.account);
      account.append(cell(journal.effectKey, "small"));
      row.append(
        account,
        cell(money(entry.debit, journal.currency)),
        cell(money(entry.credit, journal.currency)),
      );
      $("ledger-rows").append(row);
      debit += entry.debit;
      credit += entry.credit;
    }
  }
  $("ledger-balance").classList.toggle(
    "imbalanced",
    journals.some((journal) => !journal.balanced),
  );
  $("ledger-net").textContent = money(debit - credit, state.payment.currency);
  $("ledger-balance").textContent = journals.length
    ? `${journals.length} JOURNAL${journals.length > 1 ? "S" : ""} · ${journals.every((journal) => journal.balanced) ? "BALANCED" : "IMBALANCED"}`
    : "AWAITING POSTING";
  $("events").replaceChildren();
  for (const event of inspection.events || []) {
    const item = document.createElement("div");
    item.className = "event";
    const icon = cell(event.publishedAt ? "✓" : "⋯", "div");
    icon.className = "event-icon";
    const description = document.createElement("div");
    description.append(
      cell(event.type, "h3"),
      cell(
        `Sequence ${event.sequence} · ${event.attempts} publish attempt(s)`,
        "p",
      ),
      cell(new Date(event.createdAt).toLocaleTimeString(), "p"),
    );
    item.append(
      icon,
      description,
      cell(event.deliveryStatus.replaceAll("_", " "), "span"),
    );
    $("events").append(item);
  }
  for (const provider of inspection.providerOperations || []) {
    const item = document.createElement("div");
    item.className = "event";
    const icon = cell("↗", "div");
    icon.className = "event-icon";
    const detail = document.createElement("div");
    detail.append(
      cell("Simulated provider", "h3"),
      cell(provider.reference, "p"),
    );
    item.append(icon, detail, cell(provider.outcome, "span"));
    $("events").append(item);
  }
}

async function refreshRecent() {
  const result = requireSuccess(
    await api("/v1/payment_intents?limit=20", { show: false }),
  );
  const selected = state.payment?.id || "";
  $("recent").replaceChildren(
    new Option("Select a payment", ""),
    ...result.data.data.map(
      (payment) =>
        new Option(
          `${money(payment.amount, payment.currency)} · ${payment.status || payment.state} · ${payment.id.slice(-8)}`,
          payment.id,
        ),
    ),
  );
  $("recent").value = selected;
}

async function refreshPayment(id = state.payment?.id) {
  if (!id) return;
  const generation = state.generation;
  const payment = requireSuccess(
    await api(`/v1/payment_intents/${encodeURIComponent(id)}`, { show: false }),
  );
  const inspection = requireSuccess(
    await api(`/v1/payment_intents/${encodeURIComponent(id)}/inspect`, {
      show: false,
    }),
  );
  if (generation !== state.generation) return;
  renderPayment(payment.data);
  renderInspection(inspection.data);
}

async function settle(id) {
  const generation = ++state.pollGeneration;
  for (let count = 0; count < 30; count++) {
    await sleep(1000);
    if (generation !== state.pollGeneration || state.payment?.id !== id) return;
    await refreshPayment(id);
    if (generation !== state.pollGeneration || state.payment?.id !== id) return;
    const pending =
      (state.payment.status || state.payment.state) === "processing" ||
      state.inspection?.events?.some((event) => !event.publishedAt);
    if (!pending) {
      await refreshRecent();
      return;
    }
  }
  notify(
    "Polling paused after 30 seconds. Use Refresh to inspect pending work.",
  );
}

async function mutate(path, body, suppliedKey = key()) {
  const version = $("api-version").value;
  state.lastMutation = {
    path,
    body: body === undefined ? undefined : structuredClone(body),
    key: suppliedKey,
    version,
    response: undefined,
    status: undefined,
  };
  $("last-operation").textContent = `POST ${path}`;
  $("last-key").textContent = suppliedKey;
  $("retry-result").textContent =
    "Request saved. If the response is lost, replay this key.";
  const result = await api(path, {
    method: "POST",
    body,
    key: suppliedKey,
    version,
  });
  if (result.status < 500) {
    state.lastMutation.response = result.text;
    state.lastMutation.status = result.status;
  }
  requireSuccess(result);
  $("last-operation").textContent = `POST ${path}`;
  $("last-key").textContent = suppliedKey;
  $("retry-result").textContent = "Original response saved. Try a retry.";
  const id = path === "/v1/payment_intents" ? result.data.id : state.payment.id;
  await refreshPayment(id);
  await refreshRecent();
  notify(
    `HTTP ${result.status} · ${path === "/v1/payment_intents" ? "Payment intent created." : "Payment action accepted."}`,
  );
  settle(id).catch((error) => {
    if (state.payment?.id === id) notify(error.message, true);
  });
}

function updateAmount() {
  const currency = $("currency").value;
  $("currency-mark").textContent = { usd: "$", eur: "€", gbp: "£" }[currency];
  $("amount-display").textContent =
    `${(Number($("amount").value) / 100).toFixed(2)} ${currency.toUpperCase()}`;
}

$("create-key").value = key();
$("new-key").addEventListener("click", () => {
  $("create-key").value = key();
});
$("amount").addEventListener("input", updateAmount);
$("currency").addEventListener("change", updateAmount);
$("create-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(() =>
    mutate(
      "/v1/payment_intents",
      {
        amount: Number($("amount").value),
        currency: $("currency").value,
        captureMethod: $("capture").value,
      },
      $("create-key").value,
    ),
  );
});
for (const action of ["confirm", "cancel"])
  $(action).addEventListener("click", () =>
    run(() =>
      mutate(`/v1/payment_intents/${state.payment.id}/${action}`, undefined),
    ),
  );
$("capture-payment").addEventListener("click", () =>
  run(() =>
    mutate(`/v1/payment_intents/${state.payment.id}/capture`, {
      amount: state.payment.amountCapturable,
    }),
  ),
);
$("refund").addEventListener("click", () =>
  run(async () => {
    const amount = Number($("refund-amount").value);
    if (
      !Number.isSafeInteger(amount) ||
      amount < 1 ||
      amount > state.payment.amountReceived - state.payment.amountRefunded
    )
      throw new Error(
        "Enter a whole minor-unit refund amount within the remaining captured balance.",
      );
    await mutate(`/v1/payment_intents/${state.payment.id}/refunds`, { amount });
  }),
);
$("refresh").addEventListener("click", () => run(() => refreshPayment()));
$("recent").addEventListener("change", () => {
  if ($("recent").value)
    run(async () => {
      state.generation++;
      state.lastMutation = null;
      $("last-key").textContent = "";
      $("last-operation").textContent = "No mutation for the selected payment";
      $("retry-result").textContent = "Run a mutation to begin.";
      await refreshPayment($("recent").value);
    });
});
$("copy-id").addEventListener("click", () =>
  run(async () => {
    await navigator.clipboard.writeText(state.payment.id);
    notify("Payment ID copied.");
  }),
);

async function replay(count) {
  const last = state.lastMutation;
  const recovering = last.response === undefined;
  const outcomes = await Promise.allSettled(
    Array.from({ length: count }, () =>
      api(last.path, {
        method: "POST",
        body: last.body,
        key: last.key,
        version: last.version,
        show: false,
      }),
    ),
  );
  const results = outcomes
    .filter((outcome) => outcome.status === "fulfilled")
    .map((outcome) => outcome.value);
  if (!results.length)
    throw new Error(
      "No retry response arrived. The saved key is still available.",
    );
  inspectRequest(results.at(-1));
  if (last.response === undefined) {
    const recovered = results.find((result) => result.ok);
    if (recovered) {
      last.response = recovered.text;
      last.status = recovered.status;
      if (last.path === "/v1/payment_intents")
        await refreshPayment(recovered.data.id);
    }
  }
  const identical = results.filter(
    (result) =>
      result.ok &&
      result.status === last.status &&
      result.text === last.response,
  ).length;
  $("retry-result").textContent = recovering
    ? `${identical}/${count} agree with the recovered saved response`
    : `${identical}/${count} byte-identical replays`;
  await refreshPayment();
  await refreshRecent();
  if (state.payment)
    settle(state.payment.id).catch((error) => notify(error.message, true));
  notify(
    recovering
      ? `${identical}/${count} retries agree with the recovered saved response. Inspect the persisted effects.`
      : `${identical}/${count} retries returned the original HTTP ${last.status} response. The ledger and timeline show persisted effects.`,
    identical !== count,
  );
}
$("retry").addEventListener("click", () => run(() => replay(1)));
$("race").addEventListener("click", () => run(() => replay(8)));
$("conflict").addEventListener("click", () =>
  run(async () => {
    const last = state.lastMutation;
    const result = await api(last.path, {
      method: "POST",
      body: { ...last.body, amount: last.body.amount + 1 },
      key: last.key,
      version: last.version,
    });
    $("retry-result").textContent =
      `HTTP ${result.status} · ${result.data?.error?.code || "Response"}`;
    notify(
      result.status === 409
        ? "HTTP 409 · The fingerprint conflict was rejected. The original request is unchanged."
        : `Expected a conflict; received HTTP ${result.status}.`,
      result.status !== 409,
    );
    await refreshPayment();
  }),
);
$("compare").addEventListener("click", () =>
  run(async () => {
    const path = `/v1/payment_intents/${state.payment.id}`;
    const old = requireSuccess(
      await api(path, { version: "2025-01-01", show: false }),
    );
    const current = requireSuccess(
      await api(path, { version: "2026-01-01", show: false }),
    );
    if (old.data.version !== current.data.version)
      throw new Error(
        "The payment changed between reads. Refresh and compare again after processing completes.",
      );
    $("old-contract").textContent = pretty(old.data);
    $("new-contract").textContent = pretty(current.data);
    notify(
      "Both contracts fetched directly from the same payment. The legacy contract uses state; the current contract uses status.",
    );
  }),
);
$("api-version").addEventListener("change", () =>
  run(async () => {
    if (state.payment) await refreshPayment();
  }),
);
$("api-key").addEventListener("change", () =>
  run(async () => {
    state.generation++;
    state.credential = $("api-key").value;
    state.payment = null;
    state.inspection = null;
    state.lastMutation = null;
    $("intent-content").hidden = true;
    $("empty-intent").hidden = false;
    $("ledger-rows").replaceChildren();
    $("ledger-table").hidden = true;
    $("ledger-empty").hidden = false;
    $("events").replaceChildren();
    $("old-contract").textContent = "";
    $("new-contract").textContent = "";
    $("last-key").textContent = "";
    $("last-operation").textContent = "No mutation yet";
    $("retry-result").textContent = "Create an intent to begin.";
    $("request-body").textContent = "Run an action to inspect its request.";
    $("response-body").textContent =
      "Connection changed. Previous response cleared.";
    $("ledger-balance").textContent = "AWAITING POSTING";
    await refreshRecent();
    notify("Tenant connection updated.");
  }),
);
for (const node of document.querySelectorAll("[data-view]"))
  node.addEventListener("click", () => {
    for (const nav of document.querySelectorAll("[data-view]")) {
      nav.classList.toggle("active", nav === node);
      nav.setAttribute("aria-current", nav === node ? "page" : "false");
    }
    $("payments-view").hidden = node.dataset.view !== "payments";
    $("migration-view").hidden = node.dataset.view !== "migration";
    $("breadcrumb").textContent =
      node.dataset.view === "payments" ? "Playground" : "Migration lab";
  });
for (const [button, suffix, method] of [
  ["migration-status", "", "GET"],
  ["backfill", "/backfill?batchSize=500", "POST"],
  ["reconcile", "/reconcile", "GET"],
  ["gate", "/gate-cutover", "POST"],
])
  $(button).addEventListener("click", () =>
    run(async () => {
      try {
        const result = await api(`/v1/admin/migrations/payment-v2${suffix}`, {
          admin: true,
          method,
          show: false,
        });
        $("migration-output").textContent = pretty(result.data) || result.text;
        requireSuccess(result);
        notify(
          `HTTP ${result.status} · ${button.replaceAll("-", " ")} completed.`,
          false,
          "migration-notice",
        );
      } catch (error) {
        notify(error.message, true, "migration-notice");
      }
    }),
  );

syncButtons();
fetch("/actuator/health", { signal: AbortSignal.timeout(5000) })
  .then((response) => response.json())
  .then((health) => {
    $("health").textContent =
      health.status === "UP"
        ? "● Service connected"
        : `Service ${health.status}`;
  })
  .catch(() => {
    $("health").textContent = "Service unavailable";
  });
refreshRecent().catch((error) => notify(error.message, true));
