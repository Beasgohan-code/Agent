# Requested moderation command parity

Reference: user's two-page moderation list, behavior requirements, not an upstream runtime dependency.

## Current verified phase

Added `/rmwarn` (latest active warning), `/resetwarn` (all active warnings for one member) and `/resetrules` (current group's canonical rules). Group-scoped Telegram menu and live Help registrations. Warning removal accepts reply, positive ID, username or supported text mention through existing target resolver. Personal admin identity and current Restrict members permission required, protected/unknown targets refused, cross-chat replies refused; authority rechecked after target lookup. Uses awaited warning store with history flags/cleared timestamps, not history deletion. Does not lift Telegram restrictions. Rules reset uses existing Change info guard and awaited revisioned rules writer; does not erase revisions. Legacy `/unwarn`, `/resetwarns`, `/setrules clear` retained.

Evidence: first two test cases failed before handlers existed. Four cases cover removal/reset/history preservation, denied caller, real PostgreSQL member isolation/history, authoritative rules writer/guard. Initial full suite caught missing group menu scope classification; fixed without weakening assertion. Final full disposable-PG working tree **2,113 passed in 21.41s, no skips**. Compile/diff clean. Synthetic Telegram only, real disposable DB. No deployment/push.

## Remaining differences (not advertised as complete)

- Existing `/tban`, `/tmute`, `/dban`, `/dmute`, `/dkick`, `/sban`, `/smute`, `/skick` predate this phase. Their semantics are not automatically identical to the pasted list.
- `/dwarn`, `/swarn`, `/resetallwarns`, `/warnmode`, `/warntime`, `/privaterules` still missing.
- `/warnlimit` and `/rules`/`/setrules` already exist; canonical warning-policy configuration/expiry need further work before adding new configuration aliases.
- Legacy base `/mute` defaults/parsing and base `/ban` optional duration/@username support do not yet meet the entire requested list. Do not claim no-duration permanent behavior changed in this phase.
- Existing timed manual restriction variants reject sub-minute durations rather than risk Telegram interpreting short until_date as permanent. Supporting advertised 5s/30s safely would need durable scheduled release and reconciliation; do not silently relax this guard.
- No chat-wide warning reset without an audited, atomic, tenant/group-scoped implementation. No global data deletion.

Unrelated dirty workspace preserved. All changes remain local pending publication review.

## Delete/silent warning variants and publication verification

Added `/dwarn` (reply required, warn then delete that replied group message) and `/swarn` (warn with no public success confirmation; no message deletion). Current personal moderator Restrict members permission is required and rechecked, admins/unknown/self/bot targets refused. Dwarn checks both actors' Delete messages rights before warning mutation. Reasons bounded 1,000 characters, cross-chat replies rejected. Uses existing scoped restriction intent/outcome records before warning state change, no replay of already-admitted message IDs, no automatic retry after partial/unknown effects. Warning threshold escalation retains existing configured action; these variants request strict acknowledgement so absent/false Telegram results are not reported as successful escalation. Silent failures and partial cleanup/escalation are visible. Sub-minute scheduler support, policy/expiry and private rules remain unfinished.

Registered-command consistency test checks module manifests for duplicate names and missing Help descriptions. Final publication includes only reviewed FileStore/general/welcome/moderation additions plus needed shared prefix changes; unrelated Music/clone/premium/runtime pending work excluded. Local checkout ancestry reconciled to existing published branch without replacing working files. No force push, branch switch or merge.
