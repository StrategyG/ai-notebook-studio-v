import os

import pytest
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL RLS integration DB not configured")


def test_postgres_rls_hides_rows_outside_transaction_tenant() -> None:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    tenant_a = "d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e"
    tenant_b = "a8e49d50-9f30-4bde-9c6f-4a7d84b0d21c"

    try:
        with engine.connect() as connection:
            with connection.begin():
                rows_without_context = connection.execute(
                    text("SELECT tenant_id::text FROM tenant_memberships")
                ).scalars().all()
                assert rows_without_context == []

            with connection.begin():
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_a},
                )
                rows_a = connection.execute(
                    text("SELECT tenant_id::text FROM tenant_memberships")
                ).scalars().all()
                assert rows_a == [tenant_a]

            with connection.begin():
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_b},
                )
                rows_b = connection.execute(
                    text("SELECT tenant_id::text FROM tenant_memberships")
                ).scalars().all()
                assert rows_b == [tenant_b]
    finally:
        engine.dispose()
