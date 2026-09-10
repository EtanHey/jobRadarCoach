begin;

do $remove_schedule$
declare
  target_job_id bigint;
begin
  select jobid
    into target_job_id
    from cron.job
   where jobname = 'job-radar-cloud-scrape';

  if target_job_id is not null then
    perform cron.unschedule(target_job_id);
  end if;
end
$remove_schedule$;

drop function if exists scheduler_private.dispatch_cloud_scrape();

commit;
