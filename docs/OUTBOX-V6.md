# V6 Transactional Outbox Foundation

## Implemented

- Tenant-scoped outbox event model with unique idempotency key per tenant.
- Append API designed to run in the same database transaction as the business state change.
- PostgreSQL RLS policy and forced row-level security for outbox records.
- Worker claim flow uses ordered selection and `FOR UPDATE SKIP LOCKED` to avoid duplicate concurrent claims on PostgreSQL.
- Bounded lease duration, batch size, retry delay and error metadata.
- Acknowledgement and failure release require the same worker to own a non-expired lease; state transitions lock the event row.
- Failed delivery releases the event for retry and preserves bounded error metadata.
- Unit tests cover claim, lease ownership, lease expiry, acknowledgement, retry scheduling and input validation.

## Delivery semantics

The outbox provides at-least-once delivery, not exactly-once delivery. Consumers must be idempotent using event ID or the tenant-scoped idempotency key. Workers must publish externally before marking an event published; a crash between publish and acknowledgement can cause a duplicate delivery.

## Operational limitations

- No background worker, broker adapter, dead-letter queue, retry policy controller or metrics exporter is deployed yet.
- Production worker concurrency and lease-expiry recovery must be load-tested against PostgreSQL.
- Outbox payloads must contain bounded metadata and references, never bearer tokens, API keys or raw secrets.
- Runtime role requires SELECT, INSERT and UPDATE on outbox rows but must not receive DELETE or table ownership.
