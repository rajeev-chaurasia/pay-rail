# Known limits

- No real provider, card-data processing, settlement network or production
  operational qualification is included.
- Tenant reads rely on authenticated predicates. PostgreSQL RLS remains a defense-in-depth gate. The demo uses its schema
  owner; the production profile rejects ownership and elevated roles, and
  explicit runtime grants are tested separately.
- Redis admission uses a fixed window. The benchmark's offered rate must fit
  the running quota; rejected requests are not successful payment throughput.
- Outbox publication uses bounded batches of independent aggregate heads. Broker acknowledgement
  ambiguity may produce duplicates; consumers need durable deduplication.
- An indefinite provider retry can stall a Kafka partition. Production needs
  alerting, retention-aware recovery and a reviewed retry-topic policy.
- Local migration checks do not establish behavior at 100 million objects,
  across rolling binary versions or on production replicas.
- Client deadline injection alone cannot prove that a response was lost after
  commit. Deterministic tests exercise known transaction/provider boundaries;
  the shell fault campaign reports attempted deadlines honestly.
- Retained race observations demonstrate only the documented widths and
  workload. They do not establish 25K requests/second or a million-fault run.
- The local performance suite found dropped work at 100 create arrivals/s and
  an undrained outbox at the stress recovery deadline. Passing lower-rate
  observations do not establish the higher offered rates as supported capacity.
- The repository guards secret-bearing filenames and prose. This is not a
  substitute for a content-aware credential scanner or full-history audit.
- Peer approval, remote branch protection, remote CI and release are not
  established by local checks or contributor documents.
