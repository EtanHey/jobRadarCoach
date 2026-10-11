begin;
set local lock_timeout = '5s';
-- 0030 is reserved for #458. This migration is independent of its payload.
-- Keep in parity with ui/lib/job-filters.ts locationGroup.
create function public.board_location_group(value text) returns text
language sql immutable security invoker set search_path = '' as $$
  with whitespace as (select '[\s' || U&'\00a0\1680\2000-\200a\2028\2029\202f\205f\3000\feff' || ']' ws),
  normalized as (select (regexp_replace(coalesce($1,''), '^' || ws || '+|' || ws || '+$', '', 'g') collate "C") location, ws from whitespace)
  select case
    when location='' or location ~* ('^(?:remote|hybrid|on[- ]?site|worldwide|anywhere)(?:' || ws || '+(?:role|position|work))?(?:(?:' || ws || '*[/|,·—–\-]' || ws || '*|' || ws || '+or' || ws || '+|' || ws || '+)(?:remote|hybrid|on[- ]?site|worldwide|anywhere)(?:' || ws || '+(?:role|position|work))?)*$') then 'unknown'
    when location ~* '(?<![A-Za-z0-9_])(israel|tel aviv(?:-yafo)?|jerusalem|haifa|herzliya|petah tikva|ramat gan|ra[''’]?anana|yavne|kfar saba|netanya|yokneam|beer sheva|be[''’]?er sheva|caesarea|rehovot|hod hasharon|bnei brak)(?![A-Za-z0-9_])' then 'israel'
    when location ~* '(?<![A-Za-z0-9_])(united states(?: of america)?|u\.?s\.?a?\.?)(?![A-Za-z0-9_])'
      or (location ~ (',' || ws || '*[A-Z]{2}$') and location ~* ('^((San Francisco|Los Angeles|Cupertino|Walnut Creek|Hawthorne|Fremont|Mountain View|Sunnyvale|Calabasas)' || ws || '*,' || ws || '*CA|(New York|Medina|Albany|Brooklyn)' || ws || '*,' || ws || '*NY|(Seattle|Redmond|Bellevue)' || ws || '*,' || ws || '*WA|(Bastrop|San Antonio|Austin)' || ws || '*,' || ws || '*TX|(Tampa|Jacksonville|Miami)' || ws || '*,' || ws || '*FL|(Chicago|Deer Park|Lisle)' || ws || '*,' || ws || '*IL|(McLean|Reston)' || ws || '*,' || ws || '*VA|(Celina|West Chester|Dayton)' || ws || '*,' || ws || '*OH|(Philadelphia|Williamsport|Lititz|Linden|Wayne)' || ws || '*,' || ws || '*PA|(Rochester Hills|Whitehall|Troy)' || ws || '*,' || ws || '*MI|(Pound|Madison)' || ws || '*,' || ws || '*WI|(Denver|Colorado Springs)' || ws || '*,' || ws || '*CO|(Cambridge|Boston)' || ws || '*,' || ws || '*MA|(Maple Plain)' || ws || '*,' || ws || '*MN|(Greenwich)' || ws || '*,' || ws || '*CT|(Conway)' || ws || '*,' || ws || '*AR|(Fortville)' || ws || '*,' || ws || '*IN|(Atlanta)' || ws || '*,' || ws || '*GA|(Charlotte)' || ws || '*,' || ws || '*NC|(South Plainfield)' || ws || '*,' || ws || '*NJ|(Cheyenne)' || ws || '*,' || ws || '*WY|(Aiken)' || ws || '*,' || ws || '*SC|(Memphis)' || ws || '*,' || ws || '*TN|(South Burlington)' || ws || '*,' || ws || '*VT|(Scottsdale)' || ws || '*,' || ws || '*AZ|(Columbia)' || ws || '*,' || ws || '*MD|(Washington)' || ws || '*,' || ws || '*DC)$'))
      or location ~* '^(?:san francisco bay area|new york city metropolitan area|greater (?:cleveland|chicago area)|(?:austin|san antonio), texas metropolitan area|columbia, south carolina metropolitan area)$' then 'united-states'
    else 'other' end from normalized
$$;
revoke all on function public.board_location_group(text) from public,anon,authenticated;
grant execute on function public.board_location_group(text) to service_role;

-- One callable signature avoids PostgREST overload ambiguity.
drop function public.board_postings(text,text,text,text[],text,integer,text);
-- Extend the board query with the Not scored archive.
create function public.board_postings(
  filter text default 'all', availability text default 'active', fit text default '',
  statuses text[] default '{}', sort text default 'fit', "max" integer default 1000, found_within text default '',
  source text default '', work_mode text default '', location text default '',
  seniority text default '', remote boolean default null
) returns setof public.postings
language plpgsql stable security invoker set search_path = '' as $$
declare ordering text;
begin
  if $6 is null or $6 not between 1 and 1000
    or $2 is null or $2 not in ('all','active','inactive')
    or $7 is null or $7 not in ('','24h','3d','7d','30d')
    or $8 is null or length($8)>200
    or $9 is null or $9 not in ('','remote','hybrid','on-site')
    or $10 is null or $10 not in ('','israel','united-states','other')
    or $11 is null or $11 not in ('','non-senior','Intern','Junior','Mid-level','Senior','Lead / Manager','Staff / Principal','Unknown')
    or $3 is null or $3 not in ('','recommended','skip','good','scored','unscored') then
    raise exception using errcode='22023', message='Invalid board filters';
  end if;
  ordering := case $5
    when 'fit' then 'ps.score desc nulls last,date_trunc(''milliseconds'',p.sort_posted_at,''UTC'') desc,p.id'
    when 'posted' then 'date_trunc(''milliseconds'',p.sort_posted_at,''UTC'') desc,p.first_seen_at desc,p.id'
    when 'found' then 'p.first_seen_at desc,p.id'
    when 'seniority' then 'public.board_level_rank(p.seniority,p.title),p.title collate public.board_title,p.first_seen_at desc,p.id'
  end;
  if ordering is null then
    raise exception using errcode='22023', message='Invalid board sort';
  end if;
  -- Only the whitelist above is interpolated; all user values stay parameters.
  return query execute 'select p.* from public.postings p
    left join public.posting_status s on s.posting_id=p.id
    left join public.posting_scores ps on ps.posting_id=p.id
    where p.relevance_filtered=($1=''not-scored'')
      and ($1 in (''all'',''not-scored'') or coalesce(s.status,''new'')=case when $1=''new-for-me'' then ''new'' else $1 end)
      and ($8='''' or p.source=$8)
      and ($9<>'''' or $12 is null or p.remote=$12)
      and ($9='''' or coalesce(p.work_mode,case when p.remote then ''remote'' when p.remote=false then ''on-site'' end)=$9)
      and ($10='''' or public.board_location_group(p.location)=$10)
      and ($11='''' or ($11=''non-senior'' and public.board_level_rank(p.seniority,p.title) not in (3,4,5))
        or public.board_level_rank(p.seniority,p.title)=case $11 when ''Intern'' then 0 when ''Junior'' then 1
          when ''Mid-level'' then 2 when ''Senior'' then 3 when ''Lead / Manager'' then 4
          when ''Staff / Principal'' then 5 when ''Unknown'' then 6 end)
      and ($7='''' or p.first_seen_at >= now() - case $7
        when ''24h'' then interval ''24 hours'' when ''3d'' then interval ''72 hours''
        when ''7d'' then interval ''168 hours'' when ''30d'' then interval ''720 hours'' end)
      and ($2=''all'' or ($2=''active'' and p.liveness->''alive'' is distinct from ''false''::jsonb)
        or ($2=''inactive'' and p.liveness->''alive''=''false''::jsonb))
      and (coalesce(cardinality($4),0)=0 or coalesce(s.status,''new'')=any($4))
      and ($3='''' or ($3=''recommended'' and ps.score is not null and ps.recommendation in (''apply'',''referral'',''review''))
        or ($3=''skip'' and ps.score is not null and ps.recommendation=''skip'')
        or ($3=''good'' and ps.score>=60) or ($3=''scored'' and ps.score is not null)
        or ($3=''unscored'' and ps.score is null))
    order by ' || ordering || ' limit $6'
    using $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12;
end
$$;
revoke all on function public.board_postings(text,text,text,text[],text,integer,text,text,text,text,text,boolean) from public,anon,authenticated;
grant execute on function public.board_postings(text,text,text,text[],text,integer,text,text,text,text,text,boolean) to service_role;

-- Scalar array avoids the PostgREST row cap; vocabulary ignores every narrowing facet.
create function public.board_sources(filter text default 'all', availability text default 'active') returns text[]
language plpgsql stable security invoker set search_path = '' as $$
begin
  if $1 is null or $1 not in ('all','new-for-me','not-scored','new','seen','worth_checking','applied','screen','interview_technical','interview_final','offer','contract','rejected','archived','not_relevant')
    or $2 is null or $2 not in ('all','active','inactive') then
    raise exception using errcode='22023', message='Invalid source filters';
  end if;
  return array(select distinct p.source from public.postings p
    left join public.posting_status s on s.posting_id=p.id
    where p.relevance_filtered=($1='not-scored')
      and ($1 in ('all','not-scored') or coalesce(s.status,'new')=case when $1='new-for-me' then 'new' else $1 end)
      and ($2='all' or ($2='active' and p.liveness->'alive' is distinct from 'false'::jsonb)
        or ($2='inactive' and p.liveness->'alive'='false'::jsonb))
    order by p.source);
end
$$;
revoke all on function public.board_sources(text,text) from public,anon,authenticated;
grant execute on function public.board_sources(text,text) to service_role;

notify pgrst, 'reload schema';
commit;
