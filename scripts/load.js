import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const requests = new Counter("observed_requests");
const unexpected = new Counter("unexpected_responses");
const creates = new Counter("created_intents");
const mutations = new Counter("accepted_mutations");
const rejections = new Counter("rate_limit_rejections");
const started = new Counter("started_workflows");
const completed = new Counter("completed_workflows");
const profile = __ENV.PAYRAIL_PROFILE || "smoke";
const rate = Number(__ENV.PAYRAIL_RATE || 10);
const duration = __ENV.PAYRAIL_DURATION || "15s";
const base = __ENV.PAYRAIL_URL || "http://localhost:18080";
const run = __ENV.PAYRAIL_RUN_ID;
const arrival = {
  executor: "constant-arrival-rate",
  rate,
  timeUnit: "1s",
  duration,
  preAllocatedVUs: 50,
  maxVUs: 500,
  gracefulStop: "30s",
};
const stress = {
  executor: "ramping-arrival-rate",
  startRate: 200,
  timeUnit: "1s",
  stages: [
    { target: 200, duration: "20s" },
    { target: 400, duration: "1s" },
    { target: 400, duration: "20s" },
    { target: 800, duration: "1s" },
    { target: 800, duration: "20s" },
  ],
  preAllocatedVUs: 100,
  maxVUs: 500,
  gracefulStop: "30s",
};
export const options = {
  scenarios: { workload: profile === "stress" ? stress : arrival },
  systemTags: ["status", "method", "name", "scenario", "expected_response"],
  summaryTrendStats: ["avg", "min", "med", "max", "p(95)", "p(99)"],
  thresholds: {
    checks: ["rate==1"],
    unexpected_responses: [
      {
        threshold: "count==0",
        abortOnFail: profile === "stress" || profile === "target-probe",
        delayAbortEval: profile === "target-probe" ? "1s" : "20s",
      },
    ],
    dropped_iterations: [
      {
        threshold: "count==0",
        abortOnFail: profile === "target-probe",
        delayAbortEval: "1s",
      },
    ],
    http_req_duration: ["p(95)<1000", "p(99)<2000"],
  },
};

export function setup() {
  for (const metric of [
    requests,
    unexpected,
    creates,
    mutations,
    rejections,
    started,
    completed,
  ])
    metric.add(0);
  if (!run) throw new Error("A unique PAYRAIL_RUN_ID is required.");
}

function call(method, path, body, key, expected, name, version = "2026-01-01") {
  const headers = {
    Authorization: `Bearer ${__ENV.PAYRAIL_API_KEY || "pr_test_demo"}`,
    "Content-Type": "application/json",
    "PayRail-Version": version,
  };
  if (key) headers["Idempotency-Key"] = key;
  const response = http.request(
    method,
    `${base}${path}`,
    body === undefined ? null : JSON.stringify(body),
    {
      headers,
      timeout: "10s",
      tags: { name },
      responseCallback: http.expectedStatuses(expected),
    },
  );
  requests.add(1, { operation: name, status: String(response.status) });
  const accepted = response.status === expected;
  unexpected.add(accepted ? 0 : 1, {
    operation: name,
    status: String(response.status),
  });
  rejections.add(response.status === 429 ? 1 : 0);
  if (method === "POST" && response.status >= 200 && response.status < 300)
    mutations.add(1, { operation: name });
  check(response, { [`${name}: expected HTTP ${expected}`]: () => accepted });
  return response;
}

function object(response) {
  try {
    return response.json();
  } catch {
    return null;
  }
}
function successful(response) {
  return response.status >= 200 && response.status < 300;
}
function replay(response, path, body, key, name) {
  const copy = call("POST", path, body, key, response.status, name);
  const matches = check(copy, {
    [`${name}: same stored response bytes`]: () => copy.body === response.body,
  });
  return successful(copy) && matches;
}

function create(index) {
  const automatic = profile === "mixed" && index % 4 === 0;
  const body = {
    amount: 1000,
    currency: "usd",
    captureMethod: automatic ? "automatic" : "manual",
  };
  const key = `${run}-${__VU}-${__ITER}`;
  const response = call(
    "POST",
    "/v1/payment_intents",
    body,
    key,
    201,
    "create",
  );
  const payment = object(response);
  if (!successful(response) || !payment?.id) return null;
  creates.add(1);
  return { body, key, response, payment, automatic };
}

function waitForProvider(path) {
  for (let attempt = 0; attempt < 50; attempt++) {
    const response = call(
      "GET",
      path,
      undefined,
      undefined,
      200,
      "provider_poll",
    );
    const payment = object(response);
    if (payment?.status === "succeeded") return true;
    if (!successful(response)) return false;
    sleep(0.1);
  }
  check(false, { "provider completes within 5 seconds": () => false });
  return false;
}

function mixedWorkflow(work, index) {
  const path = `/v1/payment_intents/${work.payment.id}`;
  if (
    !replay(
      work.response,
      "/v1/payment_intents",
      work.body,
      work.key,
      "create_replay",
    )
  )
    return false;
  const conflict = call(
    "POST",
    "/v1/payment_intents",
    { ...work.body, amount: 1001 },
    work.key,
    409,
    "fingerprint_conflict",
  );
  if (conflict.status !== 409) return false;
  if (index % 4 === 2) {
    if (
      !successful(
        call(
          "POST",
          `${path}/cancel`,
          undefined,
          `${work.key}-cancel`,
          200,
          "cancel_created",
        ),
      )
    )
      return false;
    const rejected = call(
      "POST",
      `${path}/confirm`,
      undefined,
      `${work.key}-illegal`,
      409,
      "confirm_canceled",
    );
    return rejected.status === 409;
  }
  if (
    !successful(
      call(
        "POST",
        `${path}/confirm`,
        undefined,
        `${work.key}-confirm`,
        202,
        "confirm",
      ),
    )
  )
    return false;
  if (index % 4 === 3) {
    if (
      !successful(
        call(
          "POST",
          `${path}/cancel`,
          undefined,
          `${work.key}-cancel`,
          200,
          "cancel_authorized",
        ),
      )
    )
      return false;
    const rejected = call(
      "POST",
      `${path}/capture`,
      { amount: 1000 },
      `${work.key}-illegal`,
      409,
      "capture_canceled",
    );
    return rejected.status === 409;
  }
  if (work.automatic) {
    if (!waitForProvider(path)) return false;
  } else if (
    !successful(
      call(
        "POST",
        `${path}/capture`,
        { amount: 1000 },
        `${work.key}-capture`,
        200,
        "capture",
      ),
    )
  )
    return false;
  const old = object(
    call("GET", path, undefined, undefined, 200, "legacy_read", "2025-01-01"),
  );
  const current = object(
    call("GET", path, undefined, undefined, 200, "current_read"),
  );
  const transformed = check(current, {
    "version transforms agree": () =>
      old?.state === current?.status && old?.version === current?.version,
  });
  if (!transformed) return false;
  const refundBody = { amount: 100 };
  const refund = call(
    "POST",
    `${path}/refunds`,
    refundBody,
    `${work.key}-refund`,
    200,
    "partial_refund",
  );
  if (
    !successful(refund) ||
    !replay(
      refund,
      `${path}/refunds`,
      refundBody,
      `${work.key}-refund`,
      "refund_replay",
    )
  )
    return false;
  if (
    !successful(
      call(
        "POST",
        `${path}/refunds`,
        { amount: 900 },
        `${work.key}-remaining`,
        200,
        "full_refund",
      ),
    )
  )
    return false;
  const final = object(
    call("GET", path, undefined, undefined, 200, "final_read"),
  );
  return check(final, {
    "full refund amount and terminal state": () =>
      final?.amountRefunded === 1000 && final?.status === "refunded",
  });
}

export default function () {
  started.add(1);
  const index = __ITER + __VU;
  const work = create(index);
  if (!work) return;
  if (profile !== "mixed" || mixedWorkflow(work, index)) completed.add(1);
}

export function handleSummary(data) {
  return {
    "/results/summary.json": JSON.stringify(data, null, 2),
    stdout:
      JSON.stringify(
        {
          profile,
          requests: data.metrics.observed_requests?.values,
          latency: data.metrics.http_req_duration?.values,
          unexpected: data.metrics.unexpected_responses?.values,
        },
        null,
        2,
      ) + "\n",
  };
}
