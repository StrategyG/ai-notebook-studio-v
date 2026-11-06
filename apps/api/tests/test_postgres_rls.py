import os
import unittest
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ai_notebook_api.services.audit import append_audit_event, verify_audit_chain

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
ADMIN_DATABASE_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
TENANT_TABLES = (
    "tenant_memberships",
    "audit_events",
    "outbox_events",
    "provider_credentials",
    "rag_documents",
    "rag_document_chunks",
)


@unittest.skipUnless(DATABASE_URL, "PostgreSQL RLS integration DB not configured")
def test_postgres_rls_hides_rows_outside_transaction_tenant() -> None:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    tenant_a = "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"
    tenant_b = "a8e49d50-9f30-4bde-9c6f-4a7d84b0d21c"

    try:
        with engine.connect() as connection:
            with connection.begin():
                for table in TENANT_TABLES:
                    assert connection.execute(
                        text(f"SELECT tenant_id::text FROM {table}")
                    ).scalars().all() == []

            with connection.begin():
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_a},
                )
                for table in TENANT_TABLES:
                    assert connection.execute(
                        text(f"SELECT tenant_id::text FROM {table}")
                    ).scalars().all() == [tenant_a]

            with connection.begin():
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_b},
                )
                for table in TENANT_TABLES:
                    assert connection.execute(
                        text(f"SELECT tenant_id::text FROM {table}")
                    ).scalars().all() == [tenant_b]

            with connection.begin():
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_a},
                )
                for table, values in (
                    (
                        "audit_events",
                        "(tenant_id, sequence, actor_subject, action, resource_type, "
                        "resource_id, request_id, payload, previous_hash, event_hash) "
                        "VALUES (:tenant_id, 9, 'user', 'test', 'test', 'x', 'r', "
                        "'{}'::jsonb, repeat('0', 64), repeat('1', 64))",
                    ),
                    (
                        "outbox_events",
                        "(tenant_id, idempotency_key, event_type, aggregate_type, "
                        "aggregate_id, payload) VALUES (:tenant_id, 'cross-tenant', "
                        "'test', 'test', 'x', '{}'::jsonb)",
                    ),
                    (
                        "provider_credentials",
                        "(tenant_id, provider_id, label, key_id, nonce, encrypted_secret, "
                        "created_by) VALUES (:tenant_id, 'openai', 'cross-tenant', 'ci', "
                        "decode(repeat('00', 12), 'hex'), decode('01', 'hex'), 'user')",
                    ),
                    (
                        "rag_documents",
                        "(tenant_id, title, source_uri, source_type, embedding_model, content, content_sha256, "
                        "metadata, created_by) VALUES (:tenant_id, 'cross-tenant', "
                        "'urn:cross-tenant:test', 'manual', 'fixture-embedding-v1', 'x', repeat('a', 64), "
                        "'{}'::jsonb, 'user')",
                    ),
                ):
                    try:
                        with connection.begin_nested():
                            connection.execute(
                                text(f"INSERT INTO {table} {values}"),
                                {"tenant_id": tenant_b},
                            )
                    except DBAPIError:
                        pass
                    else:
                        raise AssertionError(f"RLS accepted cross-tenant insert into {table}")

        tenant_c = UUID("c5a19d50-9f30-4bde-9c6f-4a7d84b0d21c")
        with Session(engine) as session:
            event = append_audit_event(
                session,
                tenant_id=tenant_c,
                actor_subject="rls-integration-user",
                action="audit.integration_test",
                resource_type="test",
                resource_id="rls-test",
                request_id="rls-request",
                payload={"test": True},
            )
            sequence = event.sequence
            session.commit()
            assert sequence == 1
            assert verify_audit_chain(session, tenant_id=tenant_c)
    finally:
        engine.dispose()


@unittest.skipUnless(ADMIN_DATABASE_URL, "PostgreSQL admin DB not configured")
def test_postgres_audit_trigger_rejects_update_and_delete() -> None:
    engine = create_engine(ADMIN_DATABASE_URL, pool_pre_ping=True)
    tenant_a = "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"
    try:
        with engine.connect() as connection:
            for statement in (
                "UPDATE audit_events SET action = 'tampered' WHERE tenant_id = :tenant_id",
                "DELETE FROM audit_events WHERE tenant_id = :tenant_id",
            ):
                try:
                    connection.execute(text(statement), {"tenant_id": tenant_a})
                except DBAPIError:
                    connection.rollback()
                else:
                    raise AssertionError("audit ledger mutation was not rejected")
    finally:
        engine.dispose()
