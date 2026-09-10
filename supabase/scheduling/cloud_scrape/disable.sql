begin;

do $disable_schedule$
declare
  target_job_id bigint;
begin
  select jobid
    into target_job_id
    from cron.job
   where jobname = 'job-radar-cloud-scrape';

  if target_job_id is not null then
    perform cron.alter_job(target_job_id, active := false);
  end if;
end
$disable_schedule$;

commit;
