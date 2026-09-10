create table if not exists public.heartbeat (
  at timestamptz default now()
);

alter table public.heartbeat enable row level security;
revoke all on table public.heartbeat from public, anon, authenticated, service_role;
grant all on table public.heartbeat to service_role;
