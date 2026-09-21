create table public.posting_facts (
  posting_id uuid primary key references public.postings(id) on delete cascade,
  countries char(2)[] not null default '{}'::char(2)[],
  regions text[] not null default '{}'::text[],
  cities text[] not null default '{}'::text[],
  work_mode text not null default 'onsite',
  seniority_level text,
  seniority_source text,
  skills_mentioned text[] not null default '{}'::text[],
  link_status text not null,
  normalizer_version text not null,
  facts_sha256 text not null,
  updated_at timestamptz not null default now(),
  constraint posting_facts_work_mode check (work_mode in ('onsite', 'hybrid', 'remote')),
  constraint posting_facts_seniority_level check (seniority_level is null or seniority_level in (
    'intern', 'junior', 'mid', 'senior', 'staff_principal', 'lead_manager'
  )),
  constraint posting_facts_seniority_source check (seniority_source is null or seniority_source in (
    'extracted', 'ats', 'title'
  )),
  constraint posting_facts_link_status check (link_status in ('no_link', 'available', 'invalid_url')),
  constraint posting_facts_version_nonblank check (normalizer_version ~ '[^[:space:]]'),
  constraint posting_facts_sha256 check (facts_sha256 ~ '^[0-9a-f]{64}$')
);

create table public.location_aliases (
  alias text primary key,
  country char(2),
  region text,
  city text,
  constraint location_aliases_alias_nonblank check (alias ~ '[^[:space:]]'),
  constraint location_aliases_country_code check (country is null or country ~ '^[A-Z]{2}$')
);

insert into public.location_aliases (alias, country, region, city) values
  ('Israel', 'IL', null, null), ('IL', 'IL', null, null),
  ('Tel Aviv', 'IL', 'IL-TA', 'Tel Aviv'), ('Tel Aviv-Yafo', 'IL', 'IL-TA', 'Tel Aviv'),
  ('Tel Aviv-Yafo, Tel Aviv District, Israel', 'IL', 'IL-TA', 'Tel Aviv'),
  ('Israel - Tel Aviv', 'IL', 'IL-TA', 'Tel Aviv'), ('Tel Aviv, Israel', 'IL', 'IL-TA', 'Tel Aviv'),
  ('Israel, Tel Aviv', 'IL', 'IL-TA', 'Tel Aviv'), ('Remote - Israel', 'IL', null, null),
  ('Jerusalem', 'IL', 'IL-JM', 'Jerusalem'), ('Haifa', 'IL', 'IL-HA', 'Haifa'),
  ('Herzliya', 'IL', 'IL-TA', 'Herzliya'), ('Petah Tikva', 'IL', 'IL-TA', 'Petah Tikva'),
  ('Ramat Gan', 'IL', 'IL-TA', 'Ramat Gan'), ('Ra''anana', 'IL', 'IL-TA', 'Ra''anana'),
  ('Yavne', 'IL', 'IL-TA', 'Yavne'), ('Kfar Saba', 'IL', 'IL-TA', 'Kfar Saba'),
  ('Netanya', 'IL', 'IL-TA', 'Netanya'), ('Yokneam', 'IL', 'IL-HA', 'Yokneam'),
  ('Beer Sheva', 'IL', 'IL-D', 'Be''er Sheva'), ('Be''er Sheva', 'IL', 'IL-D', 'Be''er Sheva'),
  ('Caesarea', 'IL', 'IL-HA', 'Caesarea'), ('Rehovot', 'IL', 'IL-TA', 'Rehovot'),
  ('Hod Hasharon', 'IL', 'IL-TA', 'Hod Hasharon'), ('Bnei Brak', 'IL', 'IL-TA', 'Bnei Brak'),
  ('United States', 'US', null, null), ('United States of America', 'US', null, null),
  ('USA', 'US', null, null), ('US', 'US', null, null),
  ('San Francisco Bay Area', 'US', 'US-CA', 'San Francisco'),
  ('New York City Metropolitan Area', 'US', 'US-NY', 'New York'),
  ('Greater Cleveland', 'US', 'US-OH', 'Cleveland'), ('Greater Chicago Area', 'US', 'US-IL', 'Chicago'),
  ('Austin, Texas Metropolitan Area', 'US', 'US-TX', 'Austin'),
  ('San Antonio, Texas Metropolitan Area', 'US', 'US-TX', 'San Antonio'),
  ('Columbia, South Carolina Metropolitan Area', 'US', 'US-SC', 'Columbia'),
  ('San Francisco, CA', 'US', 'US-CA', 'San Francisco'), ('Los Angeles, CA', 'US', 'US-CA', 'Los Angeles'),
  ('Cupertino, CA', 'US', 'US-CA', 'Cupertino'), ('Walnut Creek, CA', 'US', 'US-CA', 'Walnut Creek'),
  ('Hawthorne, CA', 'US', 'US-CA', 'Hawthorne'), ('Fremont, CA', 'US', 'US-CA', 'Fremont'),
  ('Mountain View, CA', 'US', 'US-CA', 'Mountain View'), ('Sunnyvale, CA', 'US', 'US-CA', 'Sunnyvale'),
  ('Calabasas, CA', 'US', 'US-CA', 'Calabasas'), ('Medina, NY', 'US', 'US-NY', 'Medina'),
  ('Albany, NY', 'US', 'US-NY', 'Albany'), ('Brooklyn, NY', 'US', 'US-NY', 'Brooklyn'),
  ('Redmond, WA', 'US', 'US-WA', 'Redmond'), ('Bellevue, WA', 'US', 'US-WA', 'Bellevue'),
  ('Bastrop, TX', 'US', 'US-TX', 'Bastrop'), ('Tampa, FL', 'US', 'US-FL', 'Tampa'),
  ('Jacksonville, FL', 'US', 'US-FL', 'Jacksonville'), ('Miami, FL', 'US', 'US-FL', 'Miami'),
  ('Deer Park, IL', 'US', 'US-IL', 'Deer Park'), ('Lisle, IL', 'US', 'US-IL', 'Lisle'),
  ('McLean, VA', 'US', 'US-VA', 'McLean'), ('Reston, VA', 'US', 'US-VA', 'Reston'),
  ('Celina, OH', 'US', 'US-OH', 'Celina'), ('West Chester, OH', 'US', 'US-OH', 'West Chester'),
  ('Dayton, OH', 'US', 'US-OH', 'Dayton'), ('Philadelphia, PA', 'US', 'US-PA', 'Philadelphia'),
  ('Williamsport, PA', 'US', 'US-PA', 'Williamsport'), ('Lititz, PA', 'US', 'US-PA', 'Lititz'),
  ('Linden, PA', 'US', 'US-PA', 'Linden'), ('Wayne, PA', 'US', 'US-PA', 'Wayne'),
  ('Rochester Hills, MI', 'US', 'US-MI', 'Rochester Hills'), ('Whitehall, MI', 'US', 'US-MI', 'Whitehall'),
  ('Troy, MI', 'US', 'US-MI', 'Troy'), ('Pound, WI', 'US', 'US-WI', 'Pound'),
  ('Madison, WI', 'US', 'US-WI', 'Madison'), ('Colorado Springs, CO', 'US', 'US-CO', 'Colorado Springs'),
  ('Cambridge, MA', 'US', 'US-MA', 'Cambridge'), ('Maple Plain, MN', 'US', 'US-MN', 'Maple Plain'),
  ('Greenwich, CT', 'US', 'US-CT', 'Greenwich'), ('Conway, AR', 'US', 'US-AR', 'Conway'),
  ('Fortville, IN', 'US', 'US-IN', 'Fortville'), ('Atlanta, GA', 'US', 'US-GA', 'Atlanta'),
  ('Charlotte, NC', 'US', 'US-NC', 'Charlotte'), ('South Plainfield, NJ', 'US', 'US-NJ', 'South Plainfield'),
  ('Cheyenne, WY', 'US', 'US-WY', 'Cheyenne'), ('Aiken, SC', 'US', 'US-SC', 'Aiken'),
  ('Memphis, TN', 'US', 'US-TN', 'Memphis'), ('South Burlington, VT', 'US', 'US-VT', 'South Burlington'),
  ('Scottsdale, AZ', 'US', 'US-AZ', 'Scottsdale'), ('Columbia, MD', 'US', 'US-MD', 'Columbia'),
  ('Washington, DC', 'US', 'US-DC', 'Washington'),
  ('New York, NY', 'US', 'US-NY', 'New York'), ('Seattle, WA', 'US', 'US-WA', 'Seattle'),
  ('Austin, TX', 'US', 'US-TX', 'Austin'), ('San Antonio, TX', 'US', 'US-TX', 'San Antonio'),
  ('Chicago, IL', 'US', 'US-IL', 'Chicago'), ('Boston, MA', 'US', 'US-MA', 'Boston'),
  ('Denver, CO', 'US', 'US-CO', 'Denver');

alter table public.posting_facts enable row level security;
alter table public.location_aliases enable row level security;
revoke all on table public.posting_facts, public.location_aliases from public, anon, authenticated;
grant all on table public.posting_facts, public.location_aliases to service_role;
notify pgrst, 'reload schema';
