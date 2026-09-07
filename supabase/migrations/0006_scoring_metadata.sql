alter table public.posting_scores
  add column model text,
  add column scorer_version text,
  add column posting_sha256 text,
  add column profile_sha256 text,
  add column history_sha256 text,
  add column score_payload jsonb;

alter table public.posting_scores
  add constraint posting_scores_complete_metadata check (coalesce((
    model is not null and model ~ '[^[:space:]]'
    and scorer_version is not null and scorer_version ~ '[^[:space:]]'
    and posting_sha256 ~ '^[0-9a-f]{64}$'
    and profile_sha256 ~ '^[0-9a-f]{64}$'
    and history_sha256 ~ '^[0-9a-f]{64}$'
    and jsonb_typeof(score_payload) = 'object'
    and score_payload ?& array[
      'employer_type', 'seniority_real', 'fit_score', 'fit_tier',
      'recommendation', 'reasons', 'fit_line', 'fit_line_evidence_ids', 'luna_status'
    ]
    and score_payload - array[
      'employer_type', 'seniority_real', 'fit_score', 'fit_tier',
      'recommendation', 'reasons', 'fit_line', 'fit_line_evidence_ids', 'luna_status'
    ] = '{}'::jsonb
    and score_payload->'fit_score' = to_jsonb(score)
    and score_payload->'reasons' = reasons
    and jsonb_typeof(score_payload->'fit_line') = 'string'
    and score_payload->>'fit_tier' in ('strong', 'good', 'stretch', 'weak')
    and score_payload->>'recommendation' in ('apply', 'referral', 'review', 'skip')
    and score_payload->>'employer_type' in ('direct', 'agency', 'unknown')
    and jsonb_typeof(score_payload->'seniority_real') in ('boolean', 'null')
    and jsonb_typeof(score_payload->'fit_line_evidence_ids') = 'array'
    and score_payload->>'luna_status' = 'ok'
    and labels ?& array['role_type', 'seniority_match', 'remote_ok', 'red_flag_count']
    and labels - array['role_type', 'seniority_match', 'remote_ok', 'red_flag_count'] = '{}'::jsonb
    and (labels->'role_type' = 'null'::jsonb
      or labels->>'role_type' in ('frontend', 'fullstack', 'ai', 'voice'))
    and labels->>'seniority_match' in ('positive', 'mixed', 'negative', 'unknown')
    and labels->>'remote_ok' in ('positive', 'mixed', 'negative', 'unknown')
    and labels->>'red_flag_count' ~ '^[0-5]$'
  ), false)) not valid;

comment on column public.posting_scores.score_payload is
  'Coherent last-good validated Luna annotation retained for UI rendering.';
comment on column public.posting_scores.profile_sha256 is
  'Local invalidation hash of the exact professional profile snapshot; never a prompt field.';
