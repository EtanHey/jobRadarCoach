# Active microphone data contract

`public.active_mic` always has exactly one seeded row: `singleton=true`, nullable
`client_id uuid`, monotonic nonnegative `revision bigint`, and server-generated
`updated_at timestamptz`. It is published through `supabase_realtime`.

The server proxy calls these service-role-only RPCs; browser roles have no direct
relation or function access:

- `claim_active_mic(client_id uuid) -> setof active_mic` atomically replaces the
  owner and increments revision.
- `release_active_mic(client_id uuid) -> setof active_mic` locks the singleton and
  clears it only for the current owner. A stale release returns the unchanged row.
- `get_active_mic() -> setof active_mic` returns the current singleton.

Claim and release reject null client IDs with SQLSTATE `22023`. Clients should
discard responses or Realtime events below their latest observed revision.
