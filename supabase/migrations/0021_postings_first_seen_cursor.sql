-- The board list reads postings newest first (first_seen_at desc, id), and its new-roles
-- poll reads the same order past a cursor (first_seen_at > since, limit 101) every 90s.
create index if not exists postings_first_seen_at_id_idx on public.postings (first_seen_at desc, id);
