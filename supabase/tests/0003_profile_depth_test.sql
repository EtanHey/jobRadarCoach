begin;

create schema if not exists extensions;
create extension if not exists pgtap with schema extensions;
set local search_path = public, extensions;
select plan(7);

select ok(profile_value_is_valid('candidate.professional_depth', '{}'), 'empty depth is a valid unset value');
select ok(profile_value_is_valid(
  'candidate.professional_depth',
  '{"PostgreSQL":["hands-on","directed-AI"],"Kubernetes":["studied-with-AI"]}'
), 'depth supports all three labels and multiple modes');
select ok(not profile_value_is_valid(
  'candidate.professional_depth', '{"PostgreSQL":["expert"]}'
), 'unratified labels are rejected');
select ok(not profile_value_is_valid(
  'candidate.professional_depth', '{"PostgreSQL":["hands-on","hands-on"]}'
), 'duplicate labels are rejected');
select ok(not profile_value_is_valid(
  'candidate.professional_depth', '{"\t\n":["hands-on"]}'
), 'blank technology names are rejected');
select ok(profile_value_is_valid('candidate.open_to.work_modes', '["on-site"]'), 'source profile work-mode spelling remains valid');
select is((update_profile('candidate.professional_depth', '{}')).value, '{}'::jsonb, 'update_profile accepts unset depth');

select * from finish();
rollback;
