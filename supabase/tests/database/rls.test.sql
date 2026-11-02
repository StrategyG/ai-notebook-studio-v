-- pgTAP authorization tests for the initial read-only client schema.
-- Run with `supabase test db` against a disposable local Supabase database.
begin;
select plan(12);

insert into auth.users (
    id, aud, role, email, encrypted_password,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
    ('10000000-0000-4000-8000-000000000001', 'authenticated', 'authenticated', 'a@example.test', '', '{}', '{}', now(), now()),
    ('20000000-0000-4000-8000-000000000002', 'authenticated', 'authenticated', 'b@example.test', '', '{}', '{}', now(), now());

insert into public.tenants (id, name, slug, created_by) values
    ('aaaaaaaa-0000-4000-8000-000000000001', 'Tenant A', 'tenant-a', '10000000-0000-4000-8000-000000000001'),
    ('bbbbbbbb-0000-4000-8000-000000000002', 'Tenant B', 'tenant-b', '20000000-0000-4000-8000-000000000002');

insert into public.tenant_memberships (tenant_id, user_id, role) values
    ('aaaaaaaa-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', 'owner'),
    ('bbbbbbbb-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000002', 'owner');

insert into public.projects (id, tenant_id, name, slug, created_by) values
    ('aaaaaaaa-1000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000001', 'Project A', 'project-a', '10000000-0000-4000-8000-000000000001'),
    ('bbbbbbbb-1000-4000-8000-000000000002', 'bbbbbbbb-0000-4000-8000-000000000002', 'Project B', 'project-b', '20000000-0000-4000-8000-000000000002');

insert into public.project_memberships (tenant_id, project_id, user_id, role) values
    ('aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-1000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', 'member'),
    ('bbbbbbbb-0000-4000-8000-000000000002', 'bbbbbbbb-1000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000002', 'member');

insert into public.tasks (
    id, tenant_id, project_id, requesting_actor_type, requesting_actor_id,
    objective, risk_class, state, idempotency_key, timeout_seconds
) values
    ('aaaaaaaa-2000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-1000-4000-8000-000000000001', 'user', '10000000-0000-4000-8000-000000000001', 'Read project A', 'READ', 'CREATED', 'test-idempotency-key-a', 60),
    ('bbbbbbbb-2000-4000-8000-000000000002', 'bbbbbbbb-0000-4000-8000-000000000002', 'bbbbbbbb-1000-4000-8000-000000000002', 'user', '20000000-0000-4000-8000-000000000002', 'Read project B', 'READ', 'CREATED', 'test-idempotency-key-b', 60);

insert into public.audit_events (
    event_id, tenant_id, project_id, actor_type, actor_id, event_type,
    correlation_id, idempotency_key, aggregate_type, aggregate_id, aggregate_version
) values (
    'aaaaaaaa-3000-4000-8000-000000000001',
    'aaaaaaaa-0000-4000-8000-000000000001',
    'aaaaaaaa-1000-4000-8000-000000000001',
    'user', '10000000-0000-4000-8000-000000000001', 'task.created',
    'aaaaaaaa-4000-4000-8000-000000000001', 'audit-idempotency-key-a',
    'task', 'aaaaaaaa-2000-4000-8000-000000000001', 1
);

set local role authenticated;
select set_config('request.jwt.claim.sub', '10000000-0000-4000-8000-000000000001', true);
select set_config('request.jwt.claims', '{"sub":"10000000-0000-4000-8000-000000000001","role":"authenticated","aud":"authenticated"}', true);

select is((select count(*) from public.projects), 1::bigint, 'member sees only the project they belong to');
select is((select count(*) from public.tenants), 1::bigint, 'member sees only their tenant');
select is((select count(*) from public.tenant_memberships), 1::bigint, 'member sees their own membership, not other tenant members');
select is((select count(*) from public.tasks), 1::bigint, 'member sees tasks only in their project');
select is((select count(*) from public.audit_events), 0::bigint, 'ordinary project member cannot read admin-only audit stream');

select set_config('request.jwt.claim.sub', '20000000-0000-4000-8000-000000000002', true);
select set_config('request.jwt.claims', '{"sub":"20000000-0000-4000-8000-000000000002","role":"authenticated","aud":"authenticated"}', true);
select is((select count(*) from public.projects), 1::bigint, 'second tenant sees only its own project');

select set_config('request.jwt.claim.sub', '30000000-0000-4000-8000-000000000003', true);
select set_config('request.jwt.claims', '{"sub":"30000000-0000-4000-8000-000000000003","role":"authenticated","aud":"authenticated"}', true);
select is((select count(*) from public.projects), 0::bigint, 'unaffiliated user sees no projects');

select throws_ok(
    $$insert into public.audit_events (event_id, tenant_id, project_id, actor_type, actor_id, event_type, correlation_id, idempotency_key, aggregate_type, aggregate_id, aggregate_version) values (gen_random_uuid(), 'aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-1000-4000-8000-000000000001', 'user', 'x', 'test.write', gen_random_uuid(), 'forbidden-audit-write', 'task', 'x', 1)$$,
    '42501', null, 'authenticated client cannot insert audit evidence'
);
select throws_ok(
    $$update public.audit_events set event_type = 'tampered' where event_id = 'aaaaaaaa-3000-4000-8000-000000000001'$$,
    '42501', null, 'authenticated client cannot mutate audit evidence'
);
select throws_ok(
    $$insert into public.project_memberships (tenant_id, project_id, user_id, role) values ('aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-1000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000003', 'owner')$$,
    '42501', null, 'authenticated client cannot self-assign project privileges'
);

select * from extensions.finish();
rollback;
