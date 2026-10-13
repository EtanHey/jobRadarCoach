-- Operator-only rollback: first restore the application version before 0025
-- so it no longer calls board_postings. If 0026 has been applied, roll it back
-- first. Reconcile Supabase migration history through the normal release process.
-- Only derived columns/indexes/routines are removed; posting/score rows survive.
begin;
set local lock_timeout = '5s';
drop function public.board_postings(text,text,text,text[],text,integer);
drop index public.postings_board_level_idx;
drop function public.board_level_rank(text,text);
drop collation public.board_title;
drop index public.postings_sort_posted_idx;
drop index public.posting_scores_recommendation_idx;
alter table public.postings drop column sort_posted_at;
alter table public.posting_scores drop column recommendation;
notify pgrst, 'reload schema';
commit;
