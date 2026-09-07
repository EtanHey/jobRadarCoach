create table if not exists public.postings (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  external_id text not null,
  url text not null,
  title text not null,
  company text not null,
  location text,
  remote boolean,
  seniority text,
  stack text[] not null default '{}'::text[],
  salary text,
  apply_url text,
  posted_at timestamptz,
  raw_jd text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  liveness jsonb not null default '{}'::jsonb,
  constraint postings_source_external_id_key unique (source, external_id),
  constraint postings_source_nonblank check (source ~ '[^[:space:]]'),
  constraint postings_external_id_nonblank check (external_id ~ '[^[:space:]]'),
  constraint postings_url_nonblank check (url ~ '[^[:space:]]'),
  constraint postings_title_nonblank check (title ~ '[^[:space:]]'),
  constraint postings_company_nonblank check (company ~ '[^[:space:]]'),
  constraint postings_seen_order check (last_seen_at >= first_seen_at),
  constraint postings_liveness_object check (jsonb_typeof(liveness) = 'object')
);

create table if not exists public.posting_scores (
  posting_id uuid primary key references public.postings(id) on delete cascade,
  score smallint not null constraint posting_scores_score_range check (score between 0 and 100),
  reasons jsonb not null default '[]'::jsonb,
  labels jsonb not null default '{}'::jsonb,
  brain text not null,
  scored_at timestamptz not null default now(),
  constraint posting_scores_reasons_array check (jsonb_typeof(reasons) = 'array'),
  constraint posting_scores_labels_object check (jsonb_typeof(labels) = 'object'),
  constraint posting_scores_brain_nonblank check (brain ~ '[^[:space:]]')
);

create table if not exists public.posting_status (
  posting_id uuid primary key references public.postings(id) on delete cascade,
  status text not null default 'new',
  reason text,
  updated_at timestamptz not null default now(),
  constraint posting_status_value check (status in ('new', 'seen', 'saved', 'applied', 'rejected')),
  constraint posting_status_rejected_reason check (
    status <> 'rejected' or (reason is not null and reason ~ '[^[:space:]]')
  )
);

create table if not exists public.profile (
  field text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now(),
  constraint profile_field_nonblank check (field ~ '[^[:space:]]')
);

create table if not exists public.visits (
  singleton boolean primary key default true,
  last_visit_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint visits_singleton check (singleton)
);

create index if not exists postings_posted_at_idx on public.postings (posted_at desc);
create index if not exists postings_last_seen_at_idx on public.postings (last_seen_at desc);
create index if not exists posting_status_status_idx on public.posting_status (status);
create index if not exists posting_scores_score_idx on public.posting_scores (score desc);

-- This app is single-user, no-login, and tailnet-only. Keep RLS deliberately off so
-- anonymous browser SELECTs and Realtime subscriptions see rows. Browser writes go
-- through server routes; anon and authenticated receive no direct write privileges.
alter table public.postings disable row level security;
alter table public.posting_scores disable row level security;
alter table public.posting_status disable row level security;
alter table public.profile disable row level security;
alter table public.visits disable row level security;

revoke insert, update, delete, truncate, references, trigger
  on table public.postings, public.posting_scores, public.posting_status, public.profile, public.visits
  from anon, authenticated;
grant usage on schema public to anon, authenticated, service_role;
grant select
  on table public.postings, public.posting_scores, public.posting_status, public.profile, public.visits
  to anon, authenticated;
grant all
  on table public.postings, public.posting_scores, public.posting_status, public.profile, public.visits
  to service_role;

do $realtime$
declare
  table_name text;
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;

  foreach table_name in array array['postings', 'posting_scores', 'posting_status', 'profile', 'visits']
  loop
    if not exists (
      select 1
      from pg_publication_tables
      where pubname = 'supabase_realtime'
        and schemaname = 'public'
        and tablename = table_name
    ) then
      execute format('alter publication supabase_realtime add table public.%I', table_name);
    end if;
  end loop;
end
$realtime$;
