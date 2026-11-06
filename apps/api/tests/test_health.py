from fastapi import Response

from ai_notebook_api.api import health
from ai_notebook_api.core.config import Settings


def test_readiness_returns_not_ready_when_authentication_is_not_configured() -> None:
    response = Response()
    result = health.readiness(response, Settings())

    assert response.status_code == 503
    assert result["status"] == "not_ready"
    assert result["checks"]["authentication_configured"] is False


class FakeResult:
    def __init__(self, *, values=None, mapping=None, scalar=None):
        self.values = values or []
        self.mapping = mapping
        self.scalar = scalar

    def scalars(self):
        return self

    def mappings(self):
        return self

    def first(self):
        return self.mapping

    def scalar_one(self):
        return self.scalar

    def __iter__(self):
        return iter(self.values)


class FakeConnection:
    def __init__(
        self,
        *,
        role=None,
        owner=False,
        privileges=True,
        extension=True,
        protected=True,
        indexes=True,
        tables=None,
        columns=None,
        rag_columns=None,
    ):
        self.role = role or {"rolsuper": False, "rolbypassrls": False}
        self.owner = owner
        self.privileges = privileges
        self.extension = extension
        self.protected = protected
        self.indexes = indexes
        self.tables = tables or [
            "tenant_memberships",
            "audit_events",
            "outbox_events",
            "provider_credentials",
            "rag_documents",
            "rag_document_chunks",
        ]
        self.columns = columns or ["tenant_id", "issuer", "subject", "role", "status"]
        self.rag_columns = rag_columns or ["embedding_model", "metadata", "content_sha256"]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=None):
        query = str(statement)
        if "information_schema.tables" in query:
            return FakeResult(values=self.tables)
        if "information_schema.columns" in query and "rag_documents" in query:
            return FakeResult(values=self.rag_columns)
        if "information_schema.columns" in query:
            return FakeResult(values=self.columns)
        if "FROM pg_roles" in query:
            return FakeResult(mapping=self.role)
        if "relowner" in query:
            return FakeResult(scalar=self.owner)
        if "has_schema_privilege" in query:
            return FakeResult(scalar=self.privileges)
        if "pg_extension" in query:
            return FakeResult(scalar=self.extension)
        if "pg_policies" in query:
            return FakeResult(scalar=self.protected)
        if "FROM pg_indexes" in query:
            return FakeResult(scalar=self.indexes)
        return FakeResult()


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def _rag_settings() -> Settings:
    return Settings(
        database_url="postgresql://runtime:secret@db.example:5432/notebook",
        rag_enabled=True,
        embedding_api_url="https://embedding.example/v1/embeddings",
        embedding_api_key="test-key",
        embedding_model="test-model",
    )


def test_database_health_accepts_a_restricted_runtime_role_and_forced_rag_rls(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(health, "get_engine", lambda _url: FakeEngine(connection))

    assert health._database_health(_rag_settings()) == (True, True, True, True, True)


def test_database_health_rejects_superuser_bypass_and_table_owner(monkeypatch) -> None:
    connection = FakeConnection(
        role={"rolsuper": True, "rolbypassrls": False},
        owner=True,
    )
    monkeypatch.setattr(health, "get_engine", lambda _url: FakeEngine(connection))

    result = health._database_health(_rag_settings())

    assert result[0] is True
    assert result[1] is True
    assert result[2] is False
    assert result[3] is True
    assert result[4] is True


def test_database_health_rejects_missing_rls_or_required_indexes(monkeypatch) -> None:
    connection = FakeConnection(protected=False, indexes=False)
    monkeypatch.setattr(health, "get_engine", lambda _url: FakeEngine(connection))

    result = health._database_health(_rag_settings())

    assert result == (True, True, True, False, True)


def test_database_health_rejects_missing_schema_columns_and_vector_extension(monkeypatch) -> None:
    connection = FakeConnection(
        columns=["tenant_id", "subject", "role", "status"],
        rag_columns=["metadata", "content_sha256"],
        extension=False,
    )
    monkeypatch.setattr(health, "get_engine", lambda _url: FakeEngine(connection))

    result = health._database_health(_rag_settings())

    assert result[0] is True
    assert result[1] is False
    assert result[2] is True
    assert result[3] is True
    assert result[4] is True


def test_database_health_fails_closed_when_database_connection_raises(monkeypatch) -> None:
    class BrokenEngine:
        def connect(self):
            raise ConnectionError("private database detail")

    monkeypatch.setattr(health, "get_engine", lambda _url: BrokenEngine())

    assert health._database_health(_rag_settings()) == (False, False, False, False, False)


def test_readiness_returns_ready_only_when_every_dependency_check_passes(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql://runtime:secret@db.example:5432/notebook",
        auth_jwks_url="https://identity.example/jwks",
        auth_issuer="https://identity.example/",
        auth_audience="ai-notebook-api",
    )
    monkeypatch.setattr(health, "_database_health", lambda _settings: (True, True, True, True, True))
    monkeypatch.setattr(health, "identity_provider_ready", lambda _settings: True)
    response = Response()

    result = health.readiness(response, settings)

    assert response.status_code == 200
    assert result["status"] == "ready"
    assert all(result["checks"].values())


def test_readiness_returns_503_when_jwks_or_database_is_unavailable(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql://runtime:secret@db.example:5432/notebook",
        auth_jwks_url="https://identity.example/jwks",
        auth_issuer="https://identity.example/",
        auth_audience="ai-notebook-api",
    )
    monkeypatch.setattr(health, "_database_health", lambda _settings: (False, False, False, False, False))
    monkeypatch.setattr(health, "identity_provider_ready", lambda _settings: False)
    response = Response()

    result = health.readiness(response, settings)

    assert response.status_code == 503
    assert result["status"] == "not_ready"
    assert result["checks"]["database_reachable"] is False
    assert result["checks"]["jwks_reachable"] is False


def test_liveness_is_independent_of_database_and_identity_dependencies() -> None:
    assert health.liveness() == {"status": "alive"}



def test_database_health_rejects_bypassrls_even_when_role_is_not_superuser(monkeypatch) -> None:
    connection = FakeConnection(role={"rolsuper": False, "rolbypassrls": True})
    monkeypatch.setattr(health, "get_engine", lambda _url: FakeEngine(connection))

    result = health._database_health(_rag_settings())

    assert result[2] is False


def test_database_health_rejects_missing_core_tables_and_missing_privileges(monkeypatch) -> None:
    connection = FakeConnection(
        tables=["tenant_memberships", "audit_events"],
        privileges=False,
    )
    monkeypatch.setattr(health, "get_engine", lambda _url: FakeEngine(connection))

    result = health._database_health(_rag_settings())

    assert result[1] is False
    assert result[4] is False


def test_database_health_returns_false_when_persistence_is_not_configured() -> None:
    assert health._database_health(Settings()) == (False, False, False, False, False)
