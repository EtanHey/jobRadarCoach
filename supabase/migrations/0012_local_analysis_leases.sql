create table public.local_analysis_leases (
  stage text not null constraint local_analysis_leases_stage check (stage in ('extract','score')),
  posting_id uuid not null references public.postings(id) on delete cascade,
  worker_id uuid not null,
  lease_expires_at timestamptz not null,
  attempt_count integer not null constraint local_analysis_leases_attempts check (attempt_count > 0),
  next_attempt_at timestamptz not null default '-infinity',
  last_failure text constraint local_analysis_leases_failure check (
    last_failure is null or last_failure ~ '^[A-Za-z][A-Za-z0-9_]{0,63}$'
  ),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (stage, posting_id)
);

create index local_analysis_leases_ready_idx
  on public.local_analysis_leases (next_attempt_at, lease_expires_at);
alter table public.local_analysis_leases enable row level security;
revoke all on table public.local_analysis_leases from public, anon, authenticated;
grant select, insert, update, delete on table public.local_analysis_leases to service_role;

comment on table public.local_analysis_leases is
  'Crash-expiring local extraction and scoring claims with durable retry state.';
