# Suggested next improvements (not implemented promises)

Prioritize correctness over adding command aliases or decorative feature counts.

1. **Confirmed group settings writes:** move templates, greetings, filters and
   reports from batched documents into tenant/group SQL rows with awaited writes,
   version checks and explicit failure handling. Test concurrent updates and
   restart recovery before changing success wording.
2. **Transactional share grants:** unique grant IDs and atomic redemption caps,
   durable revocation and a documented policy for ambiguous/failed deliveries.
   Preserve existing signed links with a versioned compatibility path.
3. **Moderation case center:** stable SQL case numbers, retained action metadata,
   actor checks, appeal status and bounded audit retention. Include per-user
   abuse throttling and permissions rechecks for any new buttons.
4. **Safe draft workflow:** private Post Studio previews with explicit destination
   confirmation, expiry and durable scheduled jobs. Avoid accidental group-visible
   drafts and distinguish acknowledged delivery from failed audit writes.
5. **Voice recovery:** generation-fenced stream-end callbacks, diagnostics that
   distinguish cached readiness from live probe results, and opt-in recoverable
   queue snapshots without storing signed/private media URLs.
6. **Filter policies:** opt-in whole-word matching, deterministic priority and
   per-chat/user cooldowns. Keep legacy substring behavior until admins select a
   policy; bound caches and clean them on disable.
7. **Live acceptance checklist:** exercise actual commands and rich/fallback UI
   on a test bot/group, including revoked permissions, redeploy and database
   outages. A passing mocked suite or HTTP health ping is not end-to-end proof.

UI direction: shared themed panels, meaningful status/empty/error states, scoped
pagination and safe full-detail views. Reuse known emoji IDs with Unicode
fallback; do not invent IDs or hide unsolved logic behind flashy controls.
