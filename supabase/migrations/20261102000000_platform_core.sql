-- AI Notebook Studio V5 — initial multi-tenant platform foundation.
-- All direct client access is read-only in this migration. Application writes
-- must be performed by an authenticated backend that applies its own policy checks.

begin;

create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create table if not exists public.tenants (
    id uuid primary key default gen_random_uuid(),
    name text not null check (length(btrim(name)) between 1 and 160),
    slug text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    created_by uuid not null references auth.users(id) on delete restrict,
    created_at timestamptz not null default now()
);

create table if not exists public.tenant_memberships (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('owner', 'admin', 'member', 'billing_viewer')),
    created_at timestamptz not null default now(),
    unique (tenant_id, user_id),
    unique (id, tenant_id)
);

create table if not exists public.projects (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id) on delete restrict,
    name text not null check (length(btrim(name)) between 1 and 160),
    slug text not null check (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    created_by uuid not null references auth.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    unique (tenant_id, slug),
    unique (id, tenant_id)
);

create table if not exists public.project_memberships (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    project_id uuid not null,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('owner', 'admin', 'maintainer', 'member', 'viewer')),
    created_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete cascade,
    unique (project_id, user_id),
    unique (id, tenant_id, project_id)
);

create table if not exists public.workspaces (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    project_id uuid not null,
    workspace_type text not null check (
        workspace_type in ('dashboard', 'chat', 'notebook', 'repository', 'database', 'agents', 'quality', 'governance')
    ),
    name text not null check (length(btrim(name)) between 1 and 160),
    created_by uuid not null references auth.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete cascade,
    unique (project_id, workspace_type, name),
    unique (id, tenant_id, project_id)
);

create table if not exists public.tasks (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    project_id uuid not null,
    parent_task_id uuid,
    requesting_actor_type text not null check (requesting_actor_type in ('user', 'agent', 'system')),
    requesting_actor_id text not null check (length(btrim(requesting_actor_id)) between 1 and 128),
    assigned_agent_id text,
    assigned_agent_version text,
    objective text not null check (length(btrim(objective)) between 1 and 8000),
    risk_class text not null check (risk_class in ('READ', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    state text not null check (state in (
        'CREATED', 'PLANNED', 'ASSIGNED', 'RUNNING', 'REVIEW', 'VALIDATION',
        'APPROVAL', 'COMPLETED', 'WAITING', 'BLOCKED', 'FAILED', 'CANCELLED', 'EXPIRED'
    )),
    idempotency_key text not null check (length(idempotency_key) between 16 and 128),
    budget_usd numeric(12,4) not null default 0 check (budget_usd >= 0),
    timeout_seconds integer not null check (timeout_seconds between 1 and 86400),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete restrict,
    foreign key (parent_task_id, tenant_id, project_id)
        references public.tasks(id, tenant_id, project_id) on delete restrict,
    unique (id, tenant_id, project_id),
    unique (tenant_id, project_id, idempotency_key),
    check (parent_task_id is null or parent_task_id <> id)
);

create table if not exists public.task_dependencies (
    tenant_id uuid not null,
    project_id uuid not null,
    task_id uuid not null,
    depends_on_task_id uuid not null,
    created_at timestamptz not null default now(),
    primary key (tenant_id, project_id, task_id, depends_on_task_id),
    foreign key (task_id, tenant_id, project_id)
        references public.tasks(id, tenant_id, project_id) on delete cascade,
    foreign key (depends_on_task_id, tenant_id, project_id)
        references public.tasks(id, tenant_id, project_id) on delete restrict,
    check (task_id <> depends_on_task_id)
);

create table if not exists public.approvals (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    project_id uuid not null,
    requested_by text not null,
    approved_by uuid references auth.users(id) on delete restrict,
    target text not null check (length(btrim(target)) between 1 and 512),
    operation text not null check (length(btrim(operation)) between 1 and 160),
    risk_class text not null check (risk_class in ('HIGH', 'CRITICAL')),
    content_sha256 text not null check (content_sha256 ~ '^[a-f0-9]{64}$'),
    status text not null check (status in ('PENDING', 'APPROVED', 'REJECTED', 'CONSUMED', 'EXPIRED')),
    expires_at timestamptz not null,
    consumed_at timestamptz,
    created_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete restrict,
    check ((status = 'CONSUMED') = (consumed_at is not null))
);

create table if not exists public.artifacts (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    project_id uuid not null,
    storage_bucket text not null check (length(btrim(storage_bucket)) between 1 and 128),
    storage_key text not null check (length(btrim(storage_key)) between 1 and 1024),
    sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
    media_type text not null check (length(btrim(media_type)) between 1 and 128),
    trust_state text not null default 'untrusted' check (trust_state in ('untrusted', 'validated', 'trusted')),
    provenance jsonb not null default '{}'::jsonb,
    created_by text not null,
    created_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete restrict,
    unique (tenant_id, project_id, storage_bucket, storage_key)
);

create table if not exists public.agent_registry (
    id uuid primary key default gen_random_uuid(),
    agent_id text not null check (length(btrim(agent_id)) between 3 and 128),
    version text not null check (length(btrim(version)) between 1 and 64),
    tenant_id uuid references public.tenants(id) on delete cascade,
    project_id uuid,
    name text not null check (length(btrim(name)) between 1 and 120),
    description text not null check (length(btrim(description)) between 1 and 2000),
    capabilities text[] not null check (cardinality(capabilities) between 1 and 64),
    supported_task_types text[] not null check (cardinality(supported_task_types) between 1 and 64),
    supported_protocols text[] not null default array['internal']::text[],
    authentication_required boolean not null default true,
    required_permissions text[] not null default '{}'::text[],
    resource_limits jsonb not null default '{}'::jsonb,
    health text not null default 'OFFLINE' check (health in ('AVAILABLE', 'BUSY', 'DEGRADED', 'OFFLINE', 'DISABLED')),
    registered_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete cascade,
    check (project_id is null or tenant_id is not null)
);

create table if not exists public.audit_events (
    event_id uuid primary key,
    tenant_id uuid not null,
    project_id uuid not null,
    actor_type text not null check (actor_type in ('user', 'agent', 'system')),
    actor_id text not null check (length(btrim(actor_id)) between 1 and 128),
    event_type text not null check (length(btrim(event_type)) between 3 and 160),
    correlation_id uuid not null,
    idempotency_key text not null check (length(idempotency_key) between 16 and 128),
    aggregate_type text not null check (length(btrim(aggregate_type)) between 1 and 80),
    aggregate_id text not null check (length(btrim(aggregate_id)) between 1 and 160),
    aggregate_version bigint not null check (aggregate_version >= 1),
    payload jsonb not null default '{}'::jsonb,
    occurred_at timestamptz not null default now(),
    foreign key (project_id, tenant_id)
        references public.projects(id, tenant_id) on delete restrict,
    unique (tenant_id, project_id, idempotency_key)
);

create index if not exists tenant_memberships_user_idx on public.tenant_memberships(user_id, tenant_id);
create index if not exists project_memberships_user_idx on public.project_memberships(user_id, project_id);
create index if not exists projects_tenant_idx on public.projects(tenant_id, created_at desc);
create index if not exists tasks_project_state_idx on public.tasks(tenant_id, project_id, state, created_at desc);
create index if not exists approvals_project_status_idx on public.approvals(tenant_id, project_id, status, expires_at);
create index if not exists artifacts_project_created_idx on public.artifacts(tenant_id, project_id, created_at desc);
create index if not exists audit_events_project_time_idx on public.audit_events(tenant_id, project_id, occurred_at desc);

-- Audit evidence is append-only, including for privileged application roles.
create or replace function private.reject_audit_event_mutation()
returns trigger
language plpgsql
set search_path = ''
as $audit$
begin
    raise exception 'audit_events are append-only; UPDATE and DELETE are forbidden'
        using errcode = '42501';
end;
$audit$;

revoke all on function private.reject_audit_event_mutation() from public, anon, authenticated;

create trigger audit_events_append_only
    before update or delete on public.audit_events
    for each row execute function private.reject_audit_event_mutation();

-- Security-definer helpers are narrowly scoped, use a fixed search_path and
-- read only membership tables. They avoid recursive RLS policy evaluation.
create or replace function private.is_tenant_member(p_tenant_id uuid)
returns boolean language sql stable security definer
set search_path = '' set row_security = off
as $$
    select exists (
        select 1 from public.tenant_memberships tm
        where tm.tenant_id = p_tenant_id and tm.user_id = (select auth.uid())
    );
$$;

create or replace function private.has_tenant_role(p_tenant_id uuid, p_roles text[])
returns boolean language sql stable security definer
set search_path = '' set row_security = off
as $$
    select exists (
        select 1 from public.tenant_memberships tm
        where tm.tenant_id = p_tenant_id
          and tm.user_id = (select auth.uid())
          and tm.role = any(p_roles)
    );
$$;

create or replace function private.is_project_member(p_tenant_id uuid, p_project_id uuid)
returns boolean language sql stable security definer
set search_path = '' set row_security = off
as $$
    select exists (
        select 1 from public.project_memberships pm
        where pm.tenant_id = p_tenant_id
          and pm.project_id = p_project_id
          and pm.user_id = (select auth.uid())
    );
$$;

create or replace function private.has_project_role(
    p_tenant_id uuid, p_project_id uuid, p_roles text[]
)
returns boolean language sql stable security definer
set search_path = '' set row_security = off
as $$
    select exists (
        select 1 from public.project_memberships pm
        where pm.tenant_id = p_tenant_id
          and pm.project_id = p_project_id
          and pm.user_id = (select auth.uid())
          and pm.role = any(p_roles)
    );
$$;

revoke all on function private.is_tenant_member(uuid) from public, anon;
revoke all on function private.has_tenant_role(uuid, text[]) from public, anon;
revoke all on function private.is_project_member(uuid, uuid) from public, anon;
revoke all on function private.has_project_role(uuid, uuid, text[]) from public, anon;
grant execute on function private.is_tenant_member(uuid) to authenticated;
grant execute on function private.has_tenant_role(uuid, text[]) to authenticated;
grant execute on function private.is_project_member(uuid, uuid) to authenticated;
grant execute on function private.has_project_role(uuid, uuid, text[]) to authenticated;

alter table public.tenants enable row level security;
alter table public.tenant_memberships enable row level security;
alter table public.projects enable row level security;
alter table public.project_memberships enable row level security;
alter table public.workspaces enable row level security;
alter table public.tasks enable row level security;
alter table public.task_dependencies enable row level security;
alter table public.approvals enable row level security;
alter table public.artifacts enable row level security;
alter table public.agent_registry enable row level security;
alter table public.audit_events enable row level security;

create policy tenants_select_member on public.tenants
    for select to authenticated using (private.is_tenant_member(id));
create policy tenant_memberships_select_self_or_admin on public.tenant_memberships
    for select to authenticated
    using (user_id = (select auth.uid()) or private.has_tenant_role(tenant_id, array['owner', 'admin']));
create policy projects_select_project_member on public.projects
    for select to authenticated using (private.is_project_member(tenant_id, id));
create policy project_memberships_select_self_or_project_admin on public.project_memberships
    for select to authenticated
    using (
        user_id = (select auth.uid())
        or private.has_project_role(tenant_id, project_id, array['owner', 'admin'])
    );
create policy workspaces_select_project_member on public.workspaces
    for select to authenticated using (private.is_project_member(tenant_id, project_id));
create policy tasks_select_project_member on public.tasks
    for select to authenticated using (private.is_project_member(tenant_id, project_id));
create policy task_dependencies_select_project_member on public.task_dependencies
    for select to authenticated using (private.is_project_member(tenant_id, project_id));
create policy approvals_select_project_member on public.approvals
    for select to authenticated using (private.is_project_member(tenant_id, project_id));
create policy artifacts_select_project_member on public.artifacts
    for select to authenticated using (private.is_project_member(tenant_id, project_id));
create policy agent_registry_select_scoped_member on public.agent_registry
    for select to authenticated
    using (
        tenant_id is not null
        and (
            (project_id is null and private.is_tenant_member(tenant_id))
            or (project_id is not null and private.is_project_member(tenant_id, project_id))
        )
    );
create policy audit_events_select_project_admin on public.audit_events
    for select to authenticated
    using (private.has_project_role(tenant_id, project_id, array['owner', 'admin']));

-- Explicitly read-only for anon/authenticated. Mutations must go through a
-- backend with server-side authorization; service_role is never exposed to clients.
revoke all on table
    public.tenants, public.tenant_memberships, public.projects, public.project_memberships,
    public.workspaces, public.tasks, public.task_dependencies, public.approvals,
    public.artifacts, public.agent_registry, public.audit_events
from anon, authenticated;

grant select on table
    public.tenants, public.tenant_memberships, public.projects, public.project_memberships,
    public.workspaces, public.tasks, public.task_dependencies, public.approvals,
    public.artifacts, public.agent_registry, public.audit_events
to authenticated;

grant all on table
    public.tenants, public.tenant_memberships, public.projects, public.project_memberships,
    public.workspaces, public.tasks, public.task_dependencies, public.approvals,
    public.artifacts, public.agent_registry, public.audit_events
to service_role;

commit;
