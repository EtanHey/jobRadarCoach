-- Hosted access is server-only. Browser roles retain no table or routine access.
alter table public.postings enable row level security;
alter table public.posting_scores enable row level security;
alter table public.posting_status enable row level security;
alter table public.profile enable row level security;
alter table public.visits enable row level security;
alter table public.application_history enable row level security;
alter table public.posting_extractions enable row level security;
alter table public.posting_status_history enable row level security;
alter table public.active_mic enable row level security;
alter table if exists public.heartbeat enable row level security;

revoke all on schema public from public, anon, authenticated;
revoke create on schema public from service_role, supabase_realtime_admin;
grant usage on schema public to service_role, supabase_realtime_admin;

revoke all on all tables in schema public from public, anon, authenticated;
revoke all on all sequences in schema public from public, anon, authenticated;
revoke execute on function public.profile_value_is_valid(text,jsonb), public.list_new_for_me(),
  public.set_status(uuid,text,text), public.update_profile(text,jsonb), public.record_application_history(text,text,date,text,uuid), public.list_application_history(text),
  public.prepare_posting_status_change(), public.record_posting_status_change(), public.list_jobs(boolean,integer,integer,text,text,text), public.claim_active_mic(uuid),
  public.release_active_mic(uuid), public.get_active_mic() from public, anon, authenticated;

-- Supabase historically grants new public objects to API roles; remove those defaults so future grants are explicit.
alter default privileges for role postgres in schema public
  revoke all on tables from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke all on sequences from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke execute on functions from anon, authenticated, service_role;
-- PostgreSQL's built-in PUBLIC EXECUTE is global, so a schema-scoped revoke is insufficient.
alter default privileges for role postgres
  revoke execute on functions from public;

alter table public.posting_scores validate constraint posting_scores_complete_metadata;

notify pgrst, 'reload schema';
