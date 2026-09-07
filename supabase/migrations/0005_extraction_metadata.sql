create table if not exists public.posting_extractions (
  posting_id uuid primary key references public.postings(id) on delete cascade,
  brain text not null,
  model text not null,
  extractor_version text not null,
  schema_sha256 text not null,
  jd_sha256 text not null,
  fingerprint text not null,
  facts jsonb not null,
  extracted_at timestamptz not null default now(),
  constraint posting_extractions_identity_nonblank check (
    brain ~ '[^[:space:]]'
    and model ~ '[^[:space:]]'
    and extractor_version ~ '[^[:space:]]'
  ),
  constraint posting_extractions_schema_sha256 check (schema_sha256 ~ '^[0-9a-f]{64}$'),
  constraint posting_extractions_jd_sha256 check (jd_sha256 ~ '^[0-9a-f]{64}$'),
  constraint posting_extractions_fingerprint check (fingerprint ~ '^[0-9a-f]{64}$'),
  constraint posting_extractions_facts_shape check (
    jsonb_typeof(facts) = 'object'
    and facts ?& array['location', 'remote', 'seniority', 'stack', 'salary']
    and jsonb_typeof(facts->'location') = 'object'
    and (facts->'location') ?& array['value', 'evidence_quote']
    and jsonb_typeof(facts->'remote') = 'object'
    and (facts->'remote') ?& array['value', 'evidence_quote']
    and jsonb_typeof(facts->'seniority') = 'object'
    and (facts->'seniority') ?& array['value', 'evidence_quote']
    and jsonb_typeof(facts->'stack') = 'array'
    and jsonb_typeof(facts->'salary') = 'object'
    and (facts->'salary') ?& array['value', 'evidence_quote']
  )
);

alter table public.posting_extractions disable row level security;
revoke insert, update, delete, truncate, references, trigger
  on table public.posting_extractions from anon, authenticated;
grant select on table public.posting_extractions to anon, authenticated;
grant all on table public.posting_extractions to service_role;

do $realtime$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'posting_extractions'
  ) then
    alter publication supabase_realtime add table public.posting_extractions;
  end if;
end
$realtime$;

comment on table public.posting_extractions is
  'Last successful evidence-bearing extraction and exact observed processor identity per posting.';
comment on column public.posting_extractions.fingerprint is
  'Stable hash of brain, observed model, extractor version, schema hash, and captured JD hash.';
