-- Retired entry points have no application/scraper callers. Keep mark_seen and get_job_geo.
-- No CASCADE: unexpected database dependencies must stop the apply.
drop function public.list_new_for_me();
drop function public.list_jobs(boolean, integer, integer, text, text, text);
drop function public.set_seen(uuid, boolean);
drop table public.heartbeat;
notify pgrst, 'reload schema';
