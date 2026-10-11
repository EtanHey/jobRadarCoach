begin;
-- The dashboard uses get_globe_markers; retire the unused full-row RPC.
drop function public.get_globe_snapshot(text,text);
notify pgrst,'reload schema';
commit;
