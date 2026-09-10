begin;

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

do $check_vault_secret$
declare
  matching_secrets integer;
begin
  select count(*)
    into matching_secrets
    from vault.decrypted_secrets
   where name = 'job_radar_github_actions_token'
     and nullif(pg_catalog.btrim(decrypted_secret), '') is not null;

  if matching_secrets <> 1 then
    raise exception
      'Vault secret job_radar_github_actions_token must exist exactly once and be non-empty';
  end if;
end
$check_vault_secret$;

create schema if not exists scheduler_private;
revoke all on schema scheduler_private from public, anon, authenticated, service_role;

create or replace function scheduler_private.dispatch_cloud_scrape()
returns bigint
language plpgsql
security definer
set search_path = ''
as $dispatch$
declare
  github_token text;
  matching_secrets integer;
begin
  select pg_catalog.max(decrypted_secret), count(*)
    into github_token, matching_secrets
    from vault.decrypted_secrets
   where name = 'job_radar_github_actions_token';

  if matching_secrets <> 1
     or nullif(pg_catalog.btrim(github_token), '') is null then
    raise exception
      'Vault secret job_radar_github_actions_token must exist exactly once and be non-empty';
  end if;

  return net.http_post(
    url := 'https://api.github.com/repos/EtanHey/jobRadarCoach/actions/workflows/cloud-scrape.yml/dispatches',
    body := pg_catalog.jsonb_build_object('ref', 'master'),
    headers := pg_catalog.jsonb_build_object(
      'Accept', 'application/vnd.github+json',
      'Authorization', 'Bearer ' || github_token,
      'Content-Type', 'application/json',
      'X-GitHub-Api-Version', '2026-03-10'
    ),
    timeout_milliseconds := 10000
  );
end
$dispatch$;

comment on function scheduler_private.dispatch_cloud_scrape() is
  'Queues the fixed Job Radar cloud-scrape.yml workflow_dispatch request.';

revoke all on function scheduler_private.dispatch_cloud_scrape()
  from public, anon, authenticated, service_role;

-- pg_net necessarily holds outbound headers until its worker consumes the row.
-- Keep the bearer token unreadable to application roles during that interval.
revoke select on table net.http_request_queue
  from public, anon, authenticated, service_role;
revoke select on table vault.decrypted_secrets
  from public, anon, authenticated, service_role;

select cron.schedule(
  'job-radar-cloud-scrape',
  '0 */6 * * *',
  'select scheduler_private.dispatch_cloud_scrape();'
);

do $verify_schedule$
begin
  if not exists (
    select 1
      from cron.job
     where jobname = 'job-radar-cloud-scrape'
       and schedule = '0 */6 * * *'
       and command = 'select scheduler_private.dispatch_cloud_scrape();'
       and active
  ) then
    raise exception 'job-radar-cloud-scrape schedule verification failed';
  end if;
end
$verify_schedule$;

commit;
