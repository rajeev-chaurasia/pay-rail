select jsonb_build_object(
  'payments',coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from (select id,amount,currency,capture_method,status,version,amount_capturable,amount_received,amount_refunded,metadata,created_at,updated_at from payment_intents where tenant_id=:'tenant') p),'[]'::jsonb),
  'journals',coalesce((select jsonb_agg(to_jsonb(j) order by j.id) from (select id,payment_intent_id,effect_key,currency,posted from ledger_transactions where tenant_id=:'tenant') j),'[]'::jsonb),
  'entries',coalesce((select jsonb_agg(to_jsonb(e) order by e.id) from (select e.id,e.ledger_transaction_id,e.account,e.debit,e.credit from ledger_entries e join ledger_transactions j on j.id=e.ledger_transaction_id where j.tenant_id=:'tenant') e),'[]'::jsonb),
  'refunds',coalesce((select jsonb_agg(to_jsonb(r) order by r.id) from (select id,payment_intent_id,amount,status from refunds where tenant_id=:'tenant') r),'[]'::jsonb),
  'events',coalesce((select jsonb_agg(to_jsonb(o) order by o.aggregate_id,o.aggregate_sequence) from (select id,aggregate_id,aggregate_sequence,event_type,attempts,published_at from outbox_events where tenant_id=:'tenant') o),'[]'::jsonb),
  'providers',coalesce((select jsonb_agg(to_jsonb(o) order by o.payment_id) from (select split_part(stable_key,':',2) payment_id,provider_reference,status from simulated_provider_operations where left(stable_key,length(:'tenant')+1)=:'tenant'||':') o),'[]'::jsonb),
  'migration',coalesce((select jsonb_agg(to_jsonb(v) order by v.source_id) from (select source_id,amount_minor,currency_code,capture_method,lifecycle_status,capturable_minor,captured_minor,refunded_minor,source_version,metadata,source_created_at,source_updated_at from payment_intents_v2 where tenant_id=:'tenant') v),'[]'::jsonb)
);
