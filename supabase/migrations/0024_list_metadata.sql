-- Compact display metadata is derived once per description write, including existing rows.
-- Match the UI's explicit-mention and applicant-context heuristics, never infer requirements.
begin;
create function public.posting_list_metadata(description text)
returns jsonb language plpgsql immutable security invoker set search_path = '' as $fn$
declare
  technologies text[];
  phrase_patterns constant text[] := array[
    '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:(?:at least|minimum(?:[ \t]+of)?|over|around)[ \t]+)?[0-9]{1,2}(?:[ \t]*[-–—][ \t]*[0-9]{1,2})?\+?[ \t]+years?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:[ \t]+of)?(?:[ \t]+(?:[a-z][A-Za-z0-9_+/-]*,?|/)){0,7}?[ \t]+experience(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))',
    '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:(?:at least|minimum(?:[ \t]+of)?|over|around)[ \t]+)?[0-9]{1,2}(?:[ \t]*[-–—][ \t]*[0-9]{1,2})?\+?[ \t]+years?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))[ \t]+(?:in|with)[ \t]+[a-z][A-Za-z0-9_+/-]*(?:[ \t]+[a-z][A-Za-z0-9_+/-]*){0,2}',
    '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:(?:at least|minimum(?:[ \t]+of)?|over|around)[ \t]+)?[0-9]{1,2}(?:[ \t]*[-–—][ \t]*[0-9]{1,2})?\+?[ \t]+years?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:[ \t]+of)?[ \t]+(?:(?:professional|hands-on)[ \t]+){0,2}(?:(?:backend|frontend|full[- ]stack|software|platform|infrastructure|devops|data|hardware)[ \t]+)?(?:engineering|development)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))',
    '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:(?:at least|minimum(?:[ \t]+of)?|over|around)[ \t]+)?[0-9]{1,2}(?:[ \t]*[-–—][ \t]*[0-9]{1,2})?\+?[ \t]+years?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))[ \t]+(?:developing|building|working|operating|maintaining|leading|managing|designing)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
  ];
  position integer := 1;
  branch_pattern text;
  candidate_start integer;
  experience_branch boolean;
  start_at integer;
  end_at integer;
  quoted text;
  matched text;
  prefix text;
  near_context text;
  suffix text;
  short_suffix text;
  utf16_units integer;
  heading text;
  captures text[];
  section text;
  experience text := null;
begin
  select coalesce(array_agg(name order by ordinal), '{}'::text[]) into technologies
  from (values
    (0,'React Native','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))react[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+native(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (1,'React','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))react(?:\.?js)?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?![ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+native(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_])))'),
    (2,'TypeScript','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))typescript(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (3,'JavaScript','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))javascript(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (4,'Next.js','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))next\.?js(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (5,'Node.js','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))node\.?js(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (6,'Python','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))python(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (7,'PostgreSQL','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))postgres(?:ql)?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (8,'Docker','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))docker(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (9,'Kubernetes','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:kubernetes|k8s)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (10,'AWS','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:aws|amazon web services)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (11,'Azure','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:azure|microsoft cloud)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (12,'GCP','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:gcp|google cloud(?: platform)?)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (13,'Go','(?n)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))golang(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:experience|proficiency|expertise|development)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+(?:with|in|using)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+go(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:tech(?:nology)?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+stack|programming[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+languages?|languages?)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*:?[^.\n]{0,80}(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))go(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:^|[,;/|])[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*go[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?=[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:[,);/|]|$))'),
    (14,'Java','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))java(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (15,'Vue','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))vue(?:\.js|js)?(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (16,'Angular','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))angular(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (17,'C#','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))c#(?=[^A-Za-z0-9_]|$)'),
    (18,'C++','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))c\+\+(?=[^A-Za-z0-9_]|$)'),
    (19,'MongoDB','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))mongodb(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (20,'Redis','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))redis(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (21,'Kafka','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))kafka(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (22,'Elasticsearch','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))elasticsearch(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (23,'Terraform','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))terraform(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (24,'GitHub Actions','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))github actions(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (25,'Linux','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))linux(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (26,'.NET','(?:^|[^A-Za-z0-9_])(?:\.net|dotnet)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (27,'SQL Server','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))sql server(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (28,'SQL','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))sql(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?![ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+server(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_])))'),
    (29,'PHP','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))php(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (30,'Ruby','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))ruby(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (31,'Rails','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))rails(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (32,'Kotlin','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))kotlin(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (33,'Rust','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))rust(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (34,'Scala','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))scala(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (35,'Bash','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))bash(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (36,'FastAPI','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))fastapi(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (37,'Django','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))django(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (38,'Spring','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))spring boot(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))spring framework(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))java(?:[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+and|[,/])?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+spring(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))spring(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?=[,)][ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+(?:and[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+)?related technologies)'),
    (39,'Express','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))express(?:\.js|js)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))express framework(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))node\.?js[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*/[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*express(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))|(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))using express(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'),
    (40,'GraphQL','(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))graphql(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))')
  ) patterns(ordinal,name,pattern)
  where (coalesce(description,'') collate "C") ~* pattern;
  loop
    -- JS alternations take the first matching branch at the earliest position;
    -- PostgreSQL ARE alternations otherwise prefer the longest/shortest match.
    start_at := 0;
    foreach branch_pattern in array phrase_patterns loop
      candidate_start := regexp_instr(coalesce(description,'') collate "C", branch_pattern, position, 1, 0, 'i');
      if candidate_start > 0 and (start_at = 0 or candidate_start < start_at) then
        start_at := candidate_start;
        experience_branch := branch_pattern = phrase_patterns[1];
        end_at := regexp_instr(description collate "C", branch_pattern, position, 1, 1, 'i');
      end if;
    end loop;
    exit when start_at = 0;
    if experience_branch then
      -- PostgreSQL's leading greedy quantifier overrides the lazy word count.
      -- Stop at the first experience word, as JS does, before deriving the
      -- sentence-bounded suffix and advancing to the next candidate.
      end_at := regexp_instr(description collate "C",
        '(?<![A-Za-z0-9_])experience(?![A-Za-z0-9_])', start_at, 1, 1, 'i');
    end if;
    matched := substr(description,start_at,end_at-start_at);
    position := end_at;
    quoted := regexp_replace(matched collate "C",'^minimum(?:[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+of)?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+','','i');
    quoted := regexp_replace(quoted,'[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+(?:with|and|in|who|that)$','','i');
    quoted := regexp_replace(quoted,'[.,;:]+$','');
    prefix := substr(description,1,start_at-1);
    near_context := right(regexp_replace(regexp_replace(prefix,'^.*[.!?\n]','','s'),'^[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+|[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+$','','g'),180);
    -- JS slice counts UTF-16 code units, including two units for astral symbols.
    select coalesce(sum(case when ascii(substr(near_context,i,1)) > 65535 then 2 else 1 end),0)
      into utf16_units from generate_series(1,length(near_context)) i;
    while utf16_units > 180 loop
      utf16_units := utf16_units - case when ascii(left(near_context,1)) > 65535 then 2 else 1 end;
      near_context := substr(near_context,2);
    end loop;
    section := 'other';
    for captures in select regexp_matches(prefix collate "C",'^[ \t]*(?:#{1,6}[ \t]+([^\n]+)|([^\n]{1,48}))[ \t]*:?[ \t]*$','gn') loop
      heading := regexp_replace(regexp_replace(coalesce(captures[1],captures[2]),'[:#*]+$',''),'^[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+|[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+$','','g');
      if (heading collate "C") ~* '^(?:preferred(?: qualifications?)?|nice to have|bonus|advantages?)$' then
        section := 'optional';
      elsif (heading collate "C") ~* '^(?:required|requirements?|qualifications?|minimum qualifications?|what (?:we(?:''|’)re looking for|you bring|you(?:''|’)ll need|it takes)|you bring|your experience|skills?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:&|and)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*experience|who (?:you are|are you)|all about you|what we value)$' then
        section := 'applicant';
      elsif (heading collate "C") ~* '^(?:about(?: the)? company|about us|company|responsibilities|what you(?:''|’)ll do|the role|benefits|what we offer|compensation)$' then
        section := 'other';
      end if;
    end loop;
    suffix := (regexp_split_to_array(substr(description,end_at),'[.!?\n]'))[1];
    short_suffix := left(suffix,80);
    select coalesce(sum(case when ascii(substr(short_suffix,i,1)) > 65535 then 2 else 1 end),0)
      into utf16_units from generate_series(1,length(short_suffix)) i;
    while utf16_units > 80 loop
      utf16_units := utf16_units - case when ascii(right(short_suffix,1)) > 65535 then 2 else 1 end;
      short_suffix := left(short_suffix,length(short_suffix)-1);
    end loop;
    if (near_context collate "C") ~* '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:no|not|without|ideally|preferably|wish|would|nice to have)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
      or section = 'optional'
      or (suffix collate "C") ~* '^[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:[,;:–—-][ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?(?:is[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+)?(?:not required|not necessary|optional|nice to have|a plus|preferred)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
      or (near_context collate "C") ~* '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:our|the|this)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+(?:company|firm|business)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))[^.!?\n]{0,100}$'
      or (near_context collate "C") ~* '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))our team[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+(?:has|combines|brings|boasts|offers)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))[^.!?\n]{0,80}$'
      or (near_context collate "C") ~* '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))we(?:''ve| have| bring| offer| boast)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))[^.!?\n]{0,80}$'
      or (suffix collate "C") ~* '^[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:serving (?:customers|clients)|in business|as a company)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
    then continue;
    end if;
    if section = 'applicant'
      or (near_context collate "C") ~* '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:you (?:need|have|bring)|we (?:require|seek)|looking for|seeking|must(?: have)?|required|requirements?|minimum|all about you|your experience|what you bring|what you(?:''|’)ll need)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
      or (matched collate "C") ~* '^(?:at least|minimum)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
      or ((matched || ' ' || short_suffix) collate "C") ~* '(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))(?:software|engineering|developer|development|backend|frontend|full[- ]stack|devops|platform|infrastructure|data|hardware|verification|technical|programming|manufacturing|managing|product|sre)(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))'
    then experience := quoted; exit;
    end if;
  end loop;
  return jsonb_build_object('stack',technologies,'experience',experience,
    'description_available',coalesce((description collate "C") ~ '[^ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]',false));
end
$fn$;
revoke all on function public.posting_list_metadata(text) from public, anon, authenticated;
grant execute on function public.posting_list_metadata(text) to service_role;
alter table public.postings add column list_metadata jsonb
  generated always as (public.posting_list_metadata(raw_jd)) stored;
comment on column public.postings.list_metadata is 'Cached list display facts; raw_jd remains detail-only.';

create or replace function public.get_globe_snapshot(filter text default 'all', availability text default 'active')
returns jsonb language sql stable security invoker set search_path = '' as $$
  with selected as materialized (
    select p.id, p.first_seen_at,
      pg_catalog.jsonb_build_object(
        'source',p.source,'last_seen_at',p.last_seen_at,'list_metadata',p.list_metadata,
        'liveness',p.liveness,'id',p.id,'title',p.title,
        'company',p.company,'location',p.location,'remote',p.remote,
        'work_mode',p.work_mode,'seniority',p.seniority,'stack',p.stack,
        'salary',p.salary,'url',p.url,'apply_url',p.apply_url,
        'posted_at',p.posted_at,'last_published_at',p.last_published_at,'first_seen_at',p.first_seen_at) || pg_catalog.jsonb_build_object(
        'posting_status', case when s.posting_id is not null then
          pg_catalog.jsonb_build_object('status',s.status,'reason',s.reason) end,
        'posting_scores', case when ps.posting_id is not null then
          pg_catalog.jsonb_build_object('score',ps.score,'score_payload',ps.score_payload) end,
        'posting_extractions', case when e.posting_id is not null then
          pg_catalog.jsonb_build_object('posting_id',e.posting_id) end) as summary
    from public.postings p
    left join public.posting_status s on s.posting_id=p.id
    left join public.posting_scores ps on ps.posting_id=p.id
    left join public.posting_extractions e on e.posting_id=p.id
    where ($1='all' or s.status=$1 or ($1='new-for-me' and s.status='new'))
      and ($2='all' or ($2='active' and p.liveness->'alive' is distinct from 'false'::jsonb)
        or ($2='inactive' and p.liveness->'alive'='false'::jsonb))
  )
  select pg_catalog.jsonb_build_object(
    'jobs', coalesce((select pg_catalog.jsonb_agg(summary order by first_seen_at desc,id) from selected),'[]'::jsonb),
    'geo', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(g)) from public.get_job_geo(
      coalesce((select pg_catalog.array_agg(id) from selected),'{}'::uuid[])) g),'[]'::jsonb))
$$;
revoke all on function public.get_globe_snapshot(text,text) from public, anon, authenticated;
grant execute on function public.get_globe_snapshot(text,text) to service_role;
notify pgrst, 'reload schema';
commit;
