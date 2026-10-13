import http from 'k6/http';
import { check } from 'k6';
export const options = { thresholds: { checks: ['rate==1'], http_req_failed: ['rate==0'], dropped_iterations: ['count==0'] }, scenarios: { create: { executor: 'constant-arrival-rate', rate: Number(__ENV.PAYRAIL_RATE || 10), timeUnit: '1s', duration: __ENV.PAYRAIL_DURATION || '30s', preAllocatedVUs: 20, maxVUs: 500 } } };
export default function () { const n=`${__ENV.PAYRAIL_RUN_ID}-${__VU}-${__ITER}`; const r=http.post(`${__ENV.PAYRAIL_URL||'http://localhost:18080'}/v1/payment_intents`,JSON.stringify({amount:100,currency:'usd',captureMethod:'manual'}),{headers:{Authorization:`Bearer ${__ENV.PAYRAIL_API_KEY||'pr_test_demo'}`,'Idempotency-Key':`load-${n}`,'Content-Type':'application/json'}}); check(r,{'created':x=>x.status===201}); }
