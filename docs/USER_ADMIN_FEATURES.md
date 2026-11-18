# Users/stats, tagging and admin reference checklist

Source: user-provided command lists. Inventory is code-level, not proof of live Telegram permissions.

Implemented profile phase: `/myinfo` ignores replied target and renders caller; `/userinfo @username|ID` or replied user; `/info [@username|ID]` accepts explicit target in preference to reply, otherwise reply/caller. One shared existing profile renderer, no duplicated profile implementations. Five-second bounded explicit lookup, validates positive IDs/usernames and returned personal identity, raw errors redacted/type-only #Errors logs. Public Telegram fields only; no invented full/private account data. Existing moderator-only warning/approval visibility unchanged. Identity lookup can fail for inaccessible accounts.

Four tests first failed before handlers/lookup existed, now pass: myinfo self vs reply, info/userinfo explicit username and HTML safety, raw upstream ValueError redaction. Related profile/utilities/bot tests 30 passed; full disposable-PG working tree **2,125 passed in 23.69s**, no skips. No live identity lookup performed.

Existing commands from other lists include /id, /info, /promote, /demote, /pin, /unpin, /adminlist, /purge, /cancel. They are not necessarily identical to every pasted signature: e.g. custom promotion title and temporary scheduling require review.

Not implemented in this phase: AFK/mention watcher, /userstats, /recentactivity; mass tagging /all, /tagabort, /allsettings, /tagstats, /tagall, /etagall, @all/@eall; adminbox, tpromote, rights panel, admincount, silent purge, chat-photo/title/description commands and fullpromote. No fake registry/help entries. /cancel retains current job cancellation behavior, not a tagging alias. /gu remains explicitly visual demo, not evidence a tagging backend exists.

Tagging needs bounded opt-in recipient registry, no assumed complete member access or activity/presence telemetry, admin/bot exclusion, concurrent-run limits, scoped controls and rate-limit/stop/resume state. Timed promotion needs durable scheduled demotion and reconciliation, not an in-memory six-hour timer. Fullpromote cannot grant rights Telegram has not delegated to this bot. Prior source hiding and main/worker navigation requirements unchanged.

## Live group admin tools phase

Implemented `/admincount`, `/rights`, `/setchatname`, `/setchatdescription`, `/setchatphoto` via a new group-owned handler set (no duplicate existing promote/pin/purge implementations). Group/supergroup and personal identity required. Read-only count/rights require current Manage chat admin permission; metadata changes require current Change info rights for caller and bot with final caller recheck. No global Owner bypass. Count iterates Telegram's administrator filter with 10s/1,000-entry bound, includes bots/anonymous accounts numerically but exposes no hidden identities. Rights uses shared target resolver, current membership and native supplied check/cross custom emoji status cells; no fake permission toggle buttons.

Name 1–128 characters, description 1–255 (`clear` explicitly clears); photo must be a same-group, unprotected replied Telegram photo. Photo file ID grammar/type decoded via Wzgram; local-existing paths, URLs, arbitrary documents and invalid references rejected, no downloading. Network identity/read deadlines 5s; metadata mutation deadline 10s. Success only on explicit True; failures/ambiguity never retried or echoed raw. Confirmed changes use existing local audit; audit failure is separately reported, not a false failed Telegram change. Title/description content and photo reference are not logged. These setters are not a durable queued job or exactly-once delivery service; verify Telegram chat info after interrupted requests.

Ten test-first/edge cases cover registration-driven real dispatch, title/description arguments and ack, rights/count cards, denied caller/false ack, photo codec reference, paths/URLs, raw ValueError redaction/no retry, and mutation-time permission loss. First five failed before implementation; full disposable-PG working tree **2,144 passed in 20.93s**, no skips. Synthetic Telegram, no live chat changes. Earlier pending list superseded only for these five commands. AFK, activity stats, mass tagging, adminbox, timed promotion, silent purge and fullpromote remain unfinished.

## Group-scoped admin stats and recorded activity

Added `/userstats` and `/recentactivity` to existing group details command set, not duplicate user/profile handlers. Personal current Manage chat admin permission required; group/supergroup-only, no global Owner bypass. Userstats reads actual Telegram current-group member count (5s bound, positive integer acknowledgement) plus measured bot uptime and active-registry count when those services exist. Unavailable components labelled, not fabricated zero counters. Does not claim daily active users, online presence, total Telegram users or collected chat message activity.

Recentactivity is explicitly the latest ten cached current-group moderation-log entries, not complete/live Telegram activity or the complete canonical SQL audit. Displays action and UTC timestamp only, excludes reasons/message contents/actor-target IDs and any other group's history. Action labels escaped by native table renderer and capped to 64 characters; no arbitrary chat argument. Missing/corrupt/unavailable data gets redacted unavailable notice. Both use supplied semantic icons and existing navigation. No new tracking, watchers, personal message collection or SQL schema needed.

Six test-first/edge cases cover real count invocation/uptime, denied admin before count, other-group/reason isolation, no fake zero on provider failure, arguments refused before count and action HTML escaping. Four initial tests failed before registration. Full disposable-PG working suite **2,150 passed in 21.75s**, no skips. Earlier pending stats entries now superseded; AFK, tagging and the remaining admin features still pending. Synthetic Telegram count tests, not live group access proof.

## Self-service group AFK

Added `/afk [reason]` to Group with a group-only watcher under existing plugin/runtime gates. Toggles only current sender's AFK status in current group; accepts accountable non-bot identities, reason <=500 characters and valid command message ID. PostgreSQL required, scoped AFK state + unique AFK-command admission tables, serialized toggle/return writes. Duplicate command updates never toggle again. Clearing removes current stored reason/state; replay IDs retained. No presence tracking, message history or global user-away index.

Normal non-command messages/media clear caller's own status. Replies, Telegram text mentions and at most three mention entities can trigger away cards (max three target candidates); usernames resolved live with 5s deadline rather than stale username index. No full text stored. Card reason escaped by shared renderer, intentional group-visible AFK reason only. Per-away-user/group 30-second PG notification claim prevents concurrent notification storms; claim is spent before sending, ambiguous send not retried, process restarts do not reset cooldown. It is not an unbounded global anti-spam scheduler or exactly-once notification system. A notice admitted before concurrent clear can still arrive; older Telegram updates aren't a durable ordered presence feed. Disabled plugin/Telegram privacy mode may prevent the watcher seeing messages, so this is not reliable online/offline detection.

Six cases first failed on absent implementation, then cover real PG toggle/replay/group+tenant isolation, concurrent cooldown claims, clear, disabled DB, current username resolution, shared-prefix watcher exclusion, escaped away reason and invalid identity. Full working disposable-PG suite before final additional cross-tenant assertions **2,156 passed in 21.63s**, no skips. No live Telegram AFK proof. Earlier pending AFK entry superseded; mass tagging and temporary promotion remain unfinished.

## Read-only /adminbox dashboard

Added group-only `/adminbox`, current personal Manage chat admin required. Reads caller and bot membership with 5s lookup deadlines, rechecks caller before render, shows live granted permission matrix using supplied semantic check/cross IDs (Owner implicit rights). No anonymous identity substitution or global Owner bypass. Read-only; no mutation callbacks, permission grants or fake toggle buttons. Text command shortcuts from bounded curated group-admin families intersect the current command registry. Registry absence explicitly labelled, never assume unregistered timed promotion/tagging commands exist. Registered does not mean plugin enabled/authorized; card explains per-action gate and authorization still apply. Snapshot is not a promise that Telegram rights remain unchanged. No Telegram mutation or new storage.

Six regression cases: success and registered-only inventory, denial before bot lookup, invalid arguments, redacted provider failure, caller rights loss before rendering and explicit unavailable inventory. Initial four failed before implementation. Working disposable-PG full suite **2,162 passed in 21.70s**, no skips. Prior pending adminbox inventory superseded; tpromote/fullpromote, silent purge and mass tagging remain pending. No live Telegram validation.

## Silent bounded purge

Added `/spurge [count]` under Moderation ownership, not duplicate /purge registration. Personal current Delete messages admin and current bot Delete messages required, no global Owner bypass or sender_chat substitution. Final caller recheck before irreversible call. Default 10, explicit ASCII integer 1–100, deletes preceding message IDs (not reply-to range), excludes command until range request acknowledgement and audit succeed. Gaps/deleted/service/older messages can mean fewer actual removals; no promise of recent message chronology across gaps.

One bounded range request (10s deadline), then command cleanup (10s). Requires strictly positive integer Wzgram acknowledgement, never bool/None/zero. Upstream returns pts_count, not precise deleted count: audit says range request acknowledged and exact count unknown. No success card. Denial/input/permission failure, unacknowledged deletion, audit failure or command-cleanup failure produce explicit non-silent status. Audit failure retains command; ambiguous/partial result never automatically retried. Neither durable job nor exactly-once deletion. Existing legacy /purge implementation and limits unchanged; /spurge shares MAX_PURGE but uses stricter acknowledgement/authorization path. Help/menu/adminbox updated only for actual command.

17 regression cases: initial 10 absent-handler failures, then happy path/order/no success card, six invalid counts incl huge input, denied caller/bot, final caller rights loss, timeout/no retry, five invalid acknowledgement types and cleanup partial result redaction. Working PG **2,179 passed in 21.55s**, no skips. No live Telegram deletion. Prior pending silent purge entry superseded; timed/full promotion and tagging remain pending.

## Owner-confirmed full group promotion

Added `/fullpromote @username|positive_ID confirm` or same-group reply `/fullpromote confirm`. Current personal Telegram group Owner required (configured global Owner not a bypass), rechecked immediately before mutation. Target current unrestricted member only, never Owner/admin/left/restricted; self and bot rejected. Bot must currently be admin with Add administrators. Delegates explicit group-right whitelist capped individually by bot-held rights: existing manage/delete/video/restrict/info/invite/pin rights, Add administrators, topics, stories, tags, linked peers and welcome messages. Channel post/edit/direct-message flags and anonymous identity explicitly false. No arbitrary permissions editing or custom title, no implicit right escalation beyond Telegram's final authorization. Group-right support still depends on Telegram chat/API capabilities; rejection is not success. Confirmation required because recipient can delegate to further admins.

Read deadlines5s, mutation10s; exact True only, no retry after ambiguity. Audit only after acknowledgement, audit failure separately reported. Existing /promote remains restricted delegation (no Add administrators), /demote unchanged. Help/menu/adminbox reflect new command. Ten tests, six first failing preimplementation, cover Owner vs admin/global-owner role, confirmation syntax, bot ceiling, final ownership loss, existing admin refusal, false ack, timeout/redaction and same-group reply. Working realPG full suite **2,189 passed in 21.83s**, no skips. No live Telegram promotions. Prior pending fullpromote inventory superseded; durable timed promotion and tagging still unfinished.

## Limited promotion custom titles

Existing `/promote @username|positive_ID [title]` now accepts optional title; same-group reply `/promote [title]`. Title maximum16 Unicode codepoints, no control/format characters; validated before target resolution/mutation. Telegram may reject emoji or other unsupported title content. No title means existing limited promotion behavior, no title request. Text-mention target compatibility retained; /rights and /demote keep their strict shared resolver grammar. No duplicate promotion handler; limited delegation (no Add administrators/anonymous) unchanged, /fullpromote remains separate explicit group-owner command.

Mutation membership/me reads bounded5s, promotion10s. Caller permission rechecked before promotion and again before title10s. Promotion acknowledged first; only then title. Title requires exact True, no retries/rollback. Failed/unconfirmed title explicitly reports promotion confirmed, title unconfirmed; no raw API exception or fake whole-operation failure. Confirmed promotion audit failure separately reported without implying Telegram rollback, title text not stored in moderation audit. Existing no-title reply target, explicit user target and entity target remain supported. No custom title argument for /fullpromote in this phase.

11 regression cases: initial six failures plus preexisting false-ack safety pass; explicit/reply title, invalid length/newline/NUL, timeout/false-title partial success, failed promotion never title, reply no-title/entity compatibility and strict rights resolver. Working realPG full suite **2,200 passed in 24.21s**, no skips. No live Telegram promotions/title changes. Timed promotion/tagging still pending.

## Canonical warning policy and /warnmode

Added `/warnmode mute|kick|ban` (no args reads policy), sharing the existing Group-owned /warnlimit interface. Current personal Change chat info admin required for reads/writes; final permission recheck before write, no global Owner/anonymous bypass. /warnlimit accepts explicit 0/off or1–20 and optional valid action; validates whole input before changing either field. Replaces prior partial-write bug where invalid action could leave a changed threshold. Unknown/extra/oversized arguments never mutate. Threshold0 preserves chosen mode but disables escalation.

New tenant/group canonical SQL policy and immutable actor-stamped history; first access imports old chat document once under per-group advisory lock. All subsequent setting/threshold reads use canonical SQL, not potentially stale process chat cache. Concurrent field patches serialize and merge; failed writes never update local cache or claim success. Main /warn, /warnings,/warns, warning variants, blocklist warn escalation and /settings all migrated to awaited policy. Legacy synchronous helper refuses PG stores; standalone file mode retained with full input validation (not cross-process transactional). Existing /warnlimit no duplicate handler. Reads before issuing warning avoid recording a new warning when policy cannot be read. Settings unavailable status explicit; network/DB exception text redacted. Mode sets existing mute/kick/ban escalation; no automatic undo of restrictions or historical warning clearing.

Eight new regression cases; test-first policy/command cases failed before implementation. Real PG concurrent limit/action patches, tenant/group isolation, restart reads, immutable history count, stale chat-document overwrite resistance, atomic bad action, shared command state, denied caller and disconnected DB; existing variant mock seam updated to awaited reader. Final working realPG **2,208 passed in 22.08s**, no skips. **/warntime is not implemented:** warning expiry must preserve warning history and affect all active-count paths; it must not be confused with mute duration. Timed promotion/tagging remain pending.

Rollout: quiesce old warning-policy command writers before enabling new version; old-process /warnlimit changes to legacy JSON after first canonical import are intentionally ignored. No destructive migration or production data operation performed.

## Warning expiry: /warntime

Added `/warntime off` or `/warntime <duration>` (units s/m/h/d,60s–366d; no args reads shared policy). Personal current Change info admin and final mutation check as /warnmode; no anonymous/global Owner bypass. Canonical policy gains expiry_seconds default0, backward-compatible with existing two-field SQL records. No table rewrite/destructive migration. Threshold/mode settings continue merging atomically with expiry settings.

Each NEW warning snapshots expires_at at issue; old/legacy warnings without expiry remain indefinite. Changing/off setting affects only future warnings, not historical expiry timestamps. Expiry is not mute duration, unmute/unban scheduling or warning deletion. Every member warning operation expires due active records lazily, persists active=false/expired_at with reason/by/at retained, then returns/counts only active unexpired warnings. New warning threshold, base/variants/blocklist and profile warning counts all use shared awaited warning store. Reset/clear no longer count expired records as newly cleared. Group-wide reset also marks due records expired without reporting them as cleared. No periodic global scan/notification/presence watcher required; expiry works after restart and overdue rows are materialized on next read/write. Existing bounded warning-history retention remains unchanged, not an infinite archive.

11 new cases (first seven missing-command failures, one DB-required skip before PG run) cover local clock expiry/history, realPG restart/policy-change/off behavior, canonical persistence, group reset expired-count correctness, invalid duration bounds/extra/huge input, denied caller, nonretroactive policy changes and old policy compatibility. Full final suite results recorded in CODEBASE_AUDIT. Synthetic Telegram only, no live restriction changes. Prior pending warntime entry superseded; timed promotion/tagging/private-rules remain pending.

Rollout: quiesce older warning/policy writers before running the new version. Old versions do not enforce expiry; mixed-version operation is unsupported. Existing restrictions are deliberately not reversed.

## Self-service /privaterules

Added `/privaterules` in current group: personally identified current member requests canonical group rules in own DM. This is an explicit self-service delivery command, NOT a persistent group setting that forces /rules private or hides public group rules. Current live membership required (Owner/admin/member or restricted still-member); anonymous/sender_chat/bot identities, arbitrary chat/recipient arguments refused. Rule store read after membership, bounded5s; DM sends10s and positive Telegram message IDs required. Uses same native semantic-icon/escaped Unicode-safe card generator as public /rules, no duplicated stored rules or new credential source. Current group title escaped.

Empty/unavailable rules reported without fake delivery. Blocked DM or ambiguous/partial send reports acknowledged part count and asks requester to open bot/Start and inspect DM before trying again. No automatic retry, no content/group fallback, no rule body/provider text in errors/logs, no unsolicited message to other members. Existing /rules still posts public group rules. Canonical rule revisions/isolation and group plugin gates retained. Normal command-prefix handling applies.

Six test-first cases (four absent-handler failures) cover safe DM-only rendering, failure redaction/no retry/group fallback, current-member denial, invalid arguments/empty rules, multipart partial failure and anonymous denial. Full working disposable-PG **2,242 passed in19.49s**, no skips. No live Telegram delivery/production changes. This closes the explicit private-rules delivery capability, not a group-wide privacy-mode toggle; timed promotion/mass tagging remain unfinished.

## Base /mute target/duration correction

Replaced the existing registered /mute implementation (no extra/duplicate command) with shared target_and_reason resolution for positive ID, live username, text mention or reply. Parses duration AFTER target: `/mute 22 2m spam` no longer treats22 as minutes. Reply `/mute 2m spam`; duration optional default10m, bare integers minutes; reason-only text retains default. Explicit invalid numeric/duration-looking tokens rejected, not silently converted to default. Bounds60s–366d prevent Telegram treating short/oversized requests as indefinite restrictions. Legacy standalone parse_duration helper remains unchanged for other consumers/tests; this handler uses strict parsing.

Current accountable group admin with Restrict members (no global Owner bypass), protected-target lookup, bot rights check and final caller recheck before mutation. Target lookup5s; membership/me checks5s; restrict10s, exact True acknowledgement only. Self/bot/channel/anonymous targets denied. API errors redacted to type-only; ambiguous mutation never retried or audited as success. Confirmed mute audit records bounded reason, audit failure separately reported. Other base moderation commands are not silently claimed to have target/duration parity yet. Telegram owns timed restriction expiry; no new sleeping scheduler/competing writer.

Ten new test-first cases (eight failed before change), full existing moderation regression coverage maintained with fake client now exposing actual bot identity/current rights/True acknowledgement. Tests cover ID-vs-duration bug, username/reason default, five unsafe/malformed durations, false ack/no-success-audit, final permission loss and timeout/no retry/redaction. Full working PG **2,252 passed in23.24s**, no skips. No live Telegram restrictions. Timed promotion/tagging and remaining base-command parity still pending.

## Mute/unmute rich cards and authorized undo

Mute now uses shared rich Panel/kv-table (native rich transport when supported,
existing HTML/custom-emoji fallback otherwise) for member/moderator/duration/reason/
Telegram-confirmed status, plus real Unmute control when action router is available.
Input/uncertain outcome cards use same renderer. No button when router unavailable;
manual /unmute ID fallback always shown. Confirmed Telegram action is distinguished
from a later result-card delivery failure. MUTE_PERMISSIONS now specifies all audio,
document, photo, video, round-video, voice and poll sends explicitly false, replacing
deprecated aggregate media flag. Raw permission serialization tested, not live proof.

Opaque random undo tokens are per-context/bot, max200 retained,15min monotonic expiry,
one-use consumed BEFORE network side effect. Bound to result message/chat/target and
original restriction expiry; newer mute card invalidates older same-target controls.
Current personal admin and bot Restrict members permissions, protected target and
current baseline group permissions re-read before mutation; final caller recheck.
Existing restricted status and expiry must match original (2s timestamp tolerance),
else reject and ask explicit /unmute. Not durable across restart: old button says
invalid/expired and manual command remains. No global Owner bypass or callback-supplied
member/chat authority. No automatic retry or blanket all-True unmute grants. Parallel
presses can only consume once in this process. Card button does not clear warnings or
unban members. Same-expiry external restriction changes cannot be conclusively
distinguished by Telegram snapshot; this is not a transactional Telegram undo history.

/unmute now supports shared username/ID/reply resolver, live caller/bot checks, final
caller check,10s mutation and exact True acknowledgement, rich success/false-ack cards.
Original restriction isn't claimed restored: current group baseline is applied.
No arbitrary additional recipient arguments; existing profile/group policy unchanged.
Six new regression cases cover real callback route, one-use replay, wrong chat/admin
refusal, permission serialization, changed restriction refusal, username unmute/false
ack and expiry (some cases combine assertions). No live Telegram test or blanket
claim that every command has been converted. Deployed mute failure still requires
sanitized user response/error and bot permission check. Other cards remain follow-up.

## Base ban/unban rich-card review

Replaced existing base /ban and /unban handler bodies, not additional registrations.
Shared username/positive ID/text-mention/reply resolver, no unban extra arguments;
reason escaped/bounded in ban card. Current personal caller+bot Restrict members,
protected/self/bot target checks, final caller recheck,5s reads/10s mutations. Global
configured Owner cannot bypass current Telegram group rights. Exact True required,
audit only after confirmation, audit failure separate; confirmed mutation distinct
from later result-card failure. Rich Panel/kv-table and semantic lock/unlock icons,
HTML fallback via existing transport. Unban does not automatically re-add member.
No one-tap Unban button in this phase; manual /unban shown, not fake control.

Seven test-first cases (five initially failed) cover username/rich results, false
ack/no audit for both commands, bot-right denial, timeout/no retry/redaction and
final permission loss. Existing moderation fake returns explicit True to model
actual Telegram acknowledgement; denial test checks permission/no side effect.
Inventory and one-by-one review ordering in docs/COMMAND_INVENTORY.md. No live
Telegram ban/unban/production data changes; full suite evidence in CODEBASE_AUDIT.

## Base /kick rich-card review

Existing /kick now uses shared username/ID/text-mention/reply targeting and rich
Panel/kv result cards. Current personal caller and bot Restrict members required,
protected/self/bot targets rejected, final caller check, no configured-Owner bypass.
Reason escaped by shared table and capped500 characters. Shared kick_member remains
sole ban→unban implementation for all kick paths; each network step now10s bounded.
Base /kick opts into exact True acknowledgement of BOTH steps; no false success
when a step returns None/False. Existing auto/variant confirmation flags unchanged.

False/ambiguous first ban never attempts unban or records success. After confirmed
ban, failed/unconfirmed unban becomes rich Kick incomplete with safe type and
/unban ID recovery, no retry; local audit failure cannot erase that recovery status.
Successful kick means removed but not left banned, NOT automatically re-added.
No fictional re-add/undo button. Confirmed result delivery/audit failure separately
reported. Callback/Unmute behavior from prior phase unchanged.

Six test-first regression cases (initial three failures, one existing safety pass)
cover username/rich confirmed results, false ban no unban, timeout partial recovery,
bot-right denial, audit-failed partial recovery and final caller rights loss. Full
working PG **2,272 passed in24.63s**, no skips; exact source evidence in CODEBASE_AUDIT.
No live Telegram kicks. Command inventory marks kick targeted review complete;
warning family remains next, not a blanket claim all commands are polished.

## Base /warn rich card and View warnings control

Existing /warn now uses shared username/positive-ID/text-mention/reply resolver,
rich Panel/kv card with member/moderator/active count/threshold/reason/status and
separate escalation outcome. Canonical awaited warning/expiry/policy stores remain
sole writers. Current personal caller AND bot Restrict members required, protected/
self/bot targets denied, final caller check; no configured global Owner bypass.
This is intentional even with escalation disabled, matching warning-variant admin
policy. Reason trimmed/bounded500, escaped in table, not raw provider error text.

Audit failure doesn't erase recorded warning or skip threshold handling; escalation
uses confirm=True so False/None acknowledgement isn't claimed as mute/ban success.
Caller rechecked before post-record escalation. Recording distinct from subsequent
escalation/audit/result delivery uncertainty; no automatic retry/duplicate warning.
There is not a new exactly-once command admission service in this phase.

View warnings is a real read-only group callback routed under existing module gate.
Callback IDs only select the target, never confer authorization; personal current
Restrict members admin in matching callback group required, rechecked after store
read before rendering. Shows latest3 active reasons with160-character previews and
full active count, member scope only. Existing expiry can be lazily materialized by
store read, no manual warning clear/restriction undo. No router => no fake button;
manual /warns ID fallback shown. No Clear all or fake unmute button. Removal-card/
specific-warning undo binding remain follow-up; existing /rmwarn,/resetwarn commands
still explicit. Clearing warnings never claims to undo Telegram restrictions.

Seven new regression cases (initial2 failures/1 preexisting safety pass) cover
username/escaped rich card/actual callback, group/nonadmin denial, bot denial,
audit-failure recorded status, final write authority, false escalation ack and
post-read rights loss. Old group fake now models real bot identity/right/True ack;
old configured-Owner bypass test now explicitly verifies denial. Working full PG
**2,279 passed in21.79s**, no skips. Synthetic Telegram, no live warning/escalation.

## Warning-removal rich cards and consolidated /unwarn

/unwarn and /rmwarn now share one strict latest-active-warning removal path;
/resetwarn clears one target's active warnings; /resetallwarns retains explicit
confirm syntax and durable group-reset request admission. All four use rich cards
for success/no-op/confirmation/denial/failure, moderator/target/count/status fields,
shared semantic icons and explicit History retained / no Telegram restriction undo.
No duplicate handler registration or alternate warning store. Member removals use
username/positive ID/text mention/reply, no extra arguments. Current personal
Restrict members rights, protected target checks and final caller recheck;5s auth/
resolve bounds. /resetallwarns now also rechecks rights just before store reset.
No bot network rights required for purely local warning clears. No global Owner
bypass, anonymous/bot sender mutation or other-group arguments.

Committed warning clear stays reported as committed even if subsequent local audit
or result delivery fails. Provider ValueError during target lookup becomes locally
authored usage, never raw provider error text. No automatic retry. Expiry/history
semantics and atomic tenant/member/group stores unchanged; no unban/unmute request.
Existing retention cap unchanged. No new one-tap clearing controls: a safe specific-
warning undo needs atomic identity binding, not removing whichever warning is
newest when an old card is pressed. Existing View warnings control remains read-only.

Seven test-first cases (initial five failures) cover each member-removal command's
username/rich result/history, audit-failed committed result, group confirmation/
final rights loss, provider redaction and member denial. Full working realPG
**2,286 passed in21.36s**, no skips; exact staged suite in CODEBASE_AUDIT. Existing
profile and warning-reset/expiry tests preserved. No live Telegram/production changes.

## Exact-warning Remove button

New /warn cards include Remove this warning alongside View warnings, when action
router/capacity is available. Every newly issued warning now gets a random UUID
identity stored in its existing JSON history, no SQL schema rewrite. /warn supplies
that ID before issue and binds the button to that warning, not the post-issue
latest row. Automated/variant warnings also gain generated IDs through shared
store; old warning rows without IDs remain readable/clearable via explicit commands
but are never guessed or retroactively linked to an old card.

Added shared clear_warning_id operation to canonical member/group-locked warning
store: exact identity+active/unexpired test and inactive/cleared_at/cleared_by update
commit atomically, including SQL concurrency/restart. Missing/cleared/expired or
no-longer-retained ID returns False; never fall back to latest. History retained
within existing cap. Ordinary remove/reset semantics unchanged. Strict hex ID and
positive personal actor validation before storage. Existing tenant/group/member
isolation and expiry materialization preserved, no secondary writer.

Opaque token controls max200 per bot context,15min monotonic expiry, group/target/
result-message bound, consumed before store mutation. Current personal Restrict
members admin required twice, protected target checked. Concurrent/replayed presses
cannot remove another warning; SQL exact-ID mutation remains safe even if invoked
concurrently outside the process. Restart invalidates controls with explicit manual
command guidance. Stored actor/timestamp is authoritative; supplemental local audit
failure separately reported. No unmute/unban API called; clearing warning does not
reverse escalation. No automatic retry after ambiguous commit/delivery. This is
not a durable replayable UI or exactly-once warning command admission mechanism.

Eight new cases: first2 missing-API/button failures and DB-required skip before
realPG run. Local exact-vs-newer/replay, PG concurrent exact clears/restart/group+
tenant isolation, actual routed card button/replay, four wrong group/message/expired/
nonadmin cases, expired/legacy no-fallback. Full suite results in CODEBASE_AUDIT.
Synthetic callbacks/Telegram; no live moderation or production migration.

## /warnings and /warns paged reader review

Both aliases now share one handler, canonical active/expiry/policy reads and shared
username/positive-ID/text-mention/reply resolver. `/warns` alone defaults to caller;
explicit `/warns @user [page]` or reply `/warns [page]`, positive page1–999. Three
newest-first warnings per page, complete canonical reason <=500 characters, moderator
and UTC issue timestamp, active count and current threshold/action. Oversized legacy
reasons explicitly labelled preview; cached admin note preview capped240 and labelled.
No silent status/table clipping. Full retained canonical history is not deleted.

Working Previous/Next page callbacks scoped to current group/target; IDs select data,
never confer authority. Current actual membership required. Ordinary members may
query own warnings; current Restrict members admin required for another member.
Actor rights checked before reads AND after loading state before rendering. Notes/
approval metadata fetched/shown only for current authorized admin, never self-service
member view. No configured Owner/anonymous identity bypass. Read failures/redacted
provider errors produce no fake empty count. Note replies remain in the invoking
group and are visible to its members; this is request authorization, NOT private
admin-only transport. Use care with moderation notes. No direct message privacy claim.

Each page reloads current state (not frozen snapshot); new/cleared/expired records
may shift pages. Out-of-range/forged/cross-group/unauthorized presses refuse safely;
no fake button when router unavailable or only one page. Read can materialize expiry
through existing store; no manual warning clear/ban/mute side effect. Native rich
Panel/Table+existing fallback and semantic icons retained. No new registrations.

Six test-first cases (initial three failed) cover username/live pages/real callback,
other-member denial, self defaults/note privacy, final rights loss after reads,
wrong-group page without store access, invalid pages/provider redaction. Existing
moderation/profile/warning-expiry regressions pass. Final full-suite evidence in
CODEBASE_AUDIT. No live Telegram/production data changes.

## /note canonical storage and reply-parser review

Existing /note now uses shared username/positive-ID/text-mention/reply resolution.
Reply `/note first word...` no longer drops its first word. Explicit1–2000 character
text, no silent oversized-input truncation; literal text is saved, no hidden clear
keyword. Current personal Manage chat admin and final pre-save authority check,
no configured-Owner/anonymous bypass. Notes may refer to positive personal IDs,
including members no longer present; this is annotation, not Telegram moderation.
Rich confirmation shows target/moderator/character count/revision/committed status,
not note contents. No warning or restriction mutation.

New canonical SQL member-note table with serialized tenant/group/member writes,
revision and updating actor; one-time authoritative legacy-document import. Separate
immutable change metadata records actor/revision/character count, not body history
or raw note text. Current note body remains stored, not encrypted by this feature;
operators should never store credentials in moderation notes. Latest complete
committed write wins; concurrent writes don't corrupt metadata or cross scopes.
Old chat saves cannot overwrite imported note. PG direct synchronous set_note/
note_of refuse use, preventing accidental stale-store writers/readers. Local-file
standalone compatibility retained, not cross-process transactional.

/warnings admin preview now awaits canonical notes (no cached-note claim); member
self-service notes remain hidden. Admin previews are still group replies visible
to group participants, not private admin-only transport. Audit errors after commit
explicitly report saved+audit unconfirmed; no note body in audit/error/confirmation.
DB unavailability never falls back to file/cache or claims success. No retries.
Quiesce older note writers before rollout; writes to legacy document after first
canonical import intentionally ignored. No destructive migration/production access.

Six test-first cases (initial3 failed) cover full reply text/rich ack, username and
nonadmin denial, realPG legacy import/concurrent revisions/metadata/restart/group+
member+tenant isolation/stale saves, audit-failed commit, oversized input/final
rights loss and disconnected PG refusal. Full suites in CODEBASE_AUDIT. No live
Telegram note/provider calls or blanket completion claim for untouched commands.

## Approval command targeting and rich-card review

/approve, /unapprove, /approval, /approved now share one native command builder,
retaining canonical group_trust storage and atomic PG audit. Positive personal ID,
username, text mention or same-group personal reply; exactly one target, no silently
ignored trailing arguments. Personal current Manage chat authority before reads,
again immediately before writes and after reads/writes before returning details.
No global Owner override/anonymous or bot caller. No member-presence requirement:
approval records may refer to personal IDs no longer in group. No Telegram rights
change. Desired-state approve/unapprove remains idempotent, never a toggle.

Rich target/moderator/state/commit cards and bounded20-ID list pages. /approved
[page] is explicit live pagination, no inert buttons; no callback registered. No
new command aliases. Pages remain group-visible, current snapshots not frozen lists.
Approval only exempts automatic anti-spam, never manual moderation. Provider errors
are redacted, no automatic retries or fallback on configured DB failures. PG trust
revision/audit writes remain one transaction. Standalone file-mode audit errors may
occur after mutation and are truthfully unconfirmed; inspect /approval before retry.
Rights revoked after a successful write report committed with details withheld,
not a rollback. No claim of atomic authorization across Telegram and PostgreSQL.

Eleven regressions (initial7 failed/2 passed before implementation) cover target
parity, strict extras, final rights loss, post-read authorization, valid/invalid live
pages, provider error redaction, bot/anonymous/cross-chat rejection, idempotency and
local partial audit failure. Existing realPG trust concurrency/import/tenant/group
isolation/audit rollback and watcher-outage cases unchanged and rerun in full suite.
No live Telegram/production calls, migration, deployment or merge in this phase.

## /antispam command card and input review

Existing command delegates to one native builder; canonical policy storage, atomic
SQL audit and watcher semantics unchanged. Current personal Manage chat authority
checked initially, immediately before writes and after reads/writes before disclosure.
No anonymous/bot/global-Owner bypass. Commit followed by lost rights reports committed
with details withheld, not rollback. Telegram authority and DB write not atomic.

Strict command grammar: on/off/keyword-clear accept no extra text; single-valued
settings reject extra values; ASCII numeric limits2–1000 and mute30–31622400 seconds
inclusive, out-of-range rejected rather than silently clamped. Existing storage API
retains its compatibility semantics for other callers. Keywords1–200 chars remain
case-normalized literal phrases, canonical store's100-phrase cap retained. Card
shows count/enabled state instead of raw phrases, bounding output even at cap.

Rich card reports moderator/current saved or committed status, flood/duplicate
settings, links/invites, action with mute duration only when applicable, and additional
consecutive/timed flood-mode counts. /flood remains detailed flood settings command.
Explicitly not live enforcement proof: watcher must run and bot needs action rights.
Staff/approved exemptions apply to auto anti-spam, not manual moderation; /antispam
off disables additional flood modes too. No buttons, aliases or fake commands added.
Group-visible result. Redacted failures/no auto retries/no configured DB fallback.
Standalone audit failure can follow policy mutation and remains unconfirmed, never
fake success; inspect /antispam before retry. Existing PG transaction audit rollback
remains authoritative.

20 regressions (initial14 failed/1 passed before implementation) cover committed
card/actor/status, final permissions, strict extras/ranges/ASCII input, phrase privacy,
post-read authorization, impersonal callers, redacted single-attempt provider errors,
inclusive numeric bounds and additional flood-mode/off visibility. Existing realPG
policy import/concurrency/scope/audit-rollback and watcher tests rerun, not rewritten.
No live Telegram/production/deployment/merge. Full suite evidence in CODEBASE_AUDIT.

## /modlog bounded authorized reader review

Existing /modlog [page] now uses a shared native builder; no fake audit store,
callbacks or new aliases. Personal current group admin required, no Owner bypass,
anonymous/bot invocation rejected; any current group admin remains eligible (no
new Manage chat restriction). Authority checked before history access and again
before disclosure. Strict ASCII page1–4, no extras. Most recent10 merged rows,
3/page, live command pagination. No frozen snapshot guarantee.

Preserves existing local audit plus canonical anti-spam/rules/trust/restriction/
blocklist sources. Moderator IDs now shown, action outcomes retained verbatim up to
64 chars, reason previews160 chars with visible ellipsis; no text omitted silently.
Source labelled Local audit or Canonical audit (no false claim every canonical row
is successful: pending/failed cases included). No dedup without shared event IDs;
UI explicitly says overlapping records possible and window not complete audit export.
Some features have separate canonical history and are not included; this is not a
unified durable ledger. Reason previews are group-visible, not admin-only transport;
do not store credentials in moderation reasons. Notes remain content-withheld in
new note audit entries. Invalid stored timestamps/source errors fail closed with
no partial result/provider details. No automatic retries or live Telegram-state
claim. Per-source bounded timeouts/sequential reads avoid orphaned read tasks.

Nine regressions (initial8 failed) cover bounded pages/reasons/actor/source, final
authority loss, member/bot/anonymous denial before reads, provider failure redaction
without partial display/retry, empty/invalid pages, merge order and pending outcomes,
realPG committed-history group/tenant isolation. Existing local warn reason display
retained. Full suite evidence in CODEBASE_AUDIT. No production/live provider/deploy/
merge operations; this does not claim all command reviews complete.

## Command cleaning controls: in-place review

Edited existing command_cleaning.py, no new handler modules. /cleancommand and
/keepcommand retain existing aliases/storage/deletion behavior. Simpler On/Off,
moderator and Saved/Current setting card; all eight prefixes documented. Personal
Delete messages admin checked again before saving and before disclosure; bot callers
rejected. Errors redacted, no retry, no live deletion success claim. Post-save rights
loss reports saved with details withheld. Read-only calls still require current admin.
Existing realPG concurrency/audit/isolation tests rerun; two new regressions in existing
test file cover final rights, simple card, bot denial and provider error safety.
No production/live Telegram/deployment/merge. Command deletion wrapper unchanged.

### Anti-spam usage copy follow-up

Normal /antispam card now uses short line-separated examples (on/off, links off,
action mute, /flood) instead of the full grammar and audit caveat paragraph. A short
permissions/watcher/exemption note remains. Saved-policy label, validation, storage,
privacy and authorization unchanged; full command grammar still available on invalid
input. Regression updated test-first to reject the old paragraph. Existing file edited.

## Missing /tpromote: durable admission foundation (not registered)

Started genuine missing-command work instead of registering a placeholder. New SQL
intent store persists tenant/group/target/actor/bot, limited non-delegating rights,
aware expiry and explicit prepared/active/review/closed/cancelled lifecycle. Partial
unique index excludes simultaneous unresolved grants, including review state; stale
state transitions refused atomically. No local-file fallback or Telegram calls.

This is admission infrastructure only, not a usable temporary promotion feature.
No /tpromote handler/menu registration until native grant/demotion reconciliation,
shutdown/startup integration, current rights and changed-target safety are complete.
Storage state labels do not prove Telegram state. No expired task is automatically
claimed, executed or retried in this phase. No sleeping coroutine posing as durability.
Ambiguous admission errors require durable inspection before retry. Terminal rows
retained. Schema is additive; no migration/deployment/production access performed.

Two test-first cases initially failed. Real PostgreSQL six-way admission race allows
one unresolved intent, second connection reads restart state, group/tenant filters,
stale transition refusal, review blocking/new admission after closure, validation and
disconnected store refusal. Full test counts in CODEBASE_AUDIT. New module is required
missing persistence infrastructure, not another implementation of an existing command.

## /lang language picker: initial delivery, not full translation coverage

New /lang in existing core implementation, including worker navigation.100 native
language-name buttons,2 columns/12 per page/9 pages, live Previous/Next. Personal
private choice or current Manage chat admin group choice; initiating user bound
buttons, chat binding and current mutation-time/final auth. Group prefs do not edit
private prefs. Stateless authorized desired-state selection; replays by authorized
user intentionally allowed. Unknown codes/forged scope/pages rejected. No raw provider
errors, no DB fallback. Post-save rendering/authority failure identifies saved state.

Dedicated canonical tenant/scope preference table, upsert actor/time and awaited reads;
restart/group/user/tenant isolation tested. Local standalone ChatStore compatibility.
No translation provider calls/credentials/dependencies. Picker headings/save messages
translated for en/ml/hi/ta only.100 choices explicitly marked English fallback; all
other command replies currently remain English. Selection is real durable preference,
not a claim that the whole bot is localized. Next localization work must replace
hardcoded command/menu/button text with keyed catalogs preserving markup/placeholders,
then translate/review each language. No wholesale string replacement of user content,
credentials or command names. No100-language completion claim.

Tests first (initial3 failed) cover private selection/other-user denial, group rights
loss and invalid payloads, realPG restart/scope/tenant/actor/offline guards, all100
choices reachable via valid <=64-byte callbacks and explicit fallback. Menu/help and
worker registration updated, other ongoing command/timed-promotion work retained.

### Language policy correction: complete languages only (supersedes initial picker)

User rejected partial-language choices and English fallback. Removed99 incomplete
choices and partial picker-only catalogs; /lang now lists English only (the sole
full-bot source language). Unsupported codes are refused at storage admission as
well as callback validation, including old buttons. Pagination derives from actual
supported catalog length. No fallback messaging or false100-language availability.

Existing unsupported saved preferences are preserved, never rewritten to en on a
read. Preference read raises UnsupportedLanguage; picker explicitly reports the old
choice unavailable and permits explicit selection of English. No implicit selection
checkmark for old language. Missing preference defaults to source-language English;
this is not a promise to translate a previously selected language. Other bot commands
remain source English: full-bot localization infrastructure/catalog migration is still
unfinished. Future languages require full command/menu/button/error translation and
verification before entering LANGUAGES. No non-English locale claimed complete.

Updated existing four tests test-first (two initially failed), incl realPG retained
legacy unsupported preference/refusal/explicit recovery and old button rejection.
No new handler/module/provider/dependency; no deployment/production calls.

### /tpromote expiry service: tested, command still unavailable

Added reconcile_due to existing timed_promotions store; bounded tenant-local scan
and atomic one-winner claim. Durable review state is committed BEFORE external calls,
so cancellation/crash/ambiguous outcomes do not cause blind retries after restart.
Expired prepared intents go to review, not guessed successful. Active records require
same bot identity, current bot Promote right, editable admin promoted by this bot,
and exact match across every installed ChatPrivileges flag. Final fresh target check
before action. Already nonadmins close without mutation; changed/unknown/owner/promoter
mismatch remains blocked in review. All-false privilege object, strict True ack, only
then closed. False/timeout/error or DB-close failure remains review, no repeat action.
No DB means no Telegram call. Review blocks further grants until explicitly resolved.

Conservative tradeoff: provider/read outages after claim require manual review; there
is no automatic retry for uncertain outcomes. Same-right external changes between
inspection and mutation cannot be conclusively detected; Telegram+DB are not atomic.
No claim of full expiry recovery: periodic worker lifecycle, grant command, safe review
UI and startup diagnostics still required before /tpromote is registered. This phase
has no Telegram production access, deployment or handler pretending feature complete.

External source reviewed as text, never executed: Pyrogram promote_chat_member at
https://github.com/pyrogram/pyrogram/blob/30de1e21e3e8b5949971ba0bba56bb818ba43b71/pyrogram/methods/chats/promote_chat_member.py
specifies all-False demotion and bool success. Actual installed Wzgram constructor
inspected: includes newer privilege flags, all covered rather than copying upstream's
older subset. Existing licenses unchanged. RealPG tests simulate Telegram only;
concurrent claims/rights/promoter/editability/bot identity/false ack/timeouts/new flag/
prepared/closed replay and DB outage tested. This is not live-provider proof.

### /tpromote command and native worker delivered (supersedes unavailable notes)

Existing group/admin.py now owns /tpromote, no duplicate command implementation.
Supergroup/current personal Telegram owner only; no configured Owner or anonymous/bot
bypass. `/tpromote @user|positive_ID 5m`, same-group reply `/tpromote 5m`, shared
text mentions. Exactly one duration1m–365d, no titles or existing-admin changes.
Bot Add administrators/current member checked before and after durable reservation;
rights capped to normal limited group RIGHTS, no delegation/anonymous/story/channel/
new rights. All installed privilege fields explicitly false except allowed grants.
Durable intent before Telegram, strict True ack before active. Known pre-dispatch
failure cancels; uncertain dispatched grant moves to review, no repeat promotion.

Native task in lease-owned main/clone AgentBot lifecycle starts after connection,
scans up to20 due intents every30s, cancellation awaited before client teardown;
restart scans SQL, no per-user sleeping tasks. Offline/scan failure logs safe #Errors
and retries only scan, never ambiguous Telegram mutation. Commands refuse grants
without running recovery or PostgreSQL. Bot must remain online and retain rights;
expiry is not Telegram-native and can be delayed by downtime/batches. No guarantee
all expired users demoted: changed/uncertain state deliberately stops for review.

`/tpromote status` shows newest10 group-scoped request IDs/state/deadlines to current
owner, reauthorized before disclosure. `/tpromote resolve ID` closes review only after
fresh target no longer admin + owner recheck, changes no Telegram rights. Group-visible
status contains no note/credential content. Uncertain rows never silently released.
No hidden retries. Recovery service's same-right external-change race limitation
still applies. Fixed-point finite task shutdown; cancelled in-flight action leaves
review. No production/deployment/live Telegram claims.

Five new tests (initial2 missing command/worker tests failed; realPG grant test
requires PostgreSQL): full grant/expiry/status, false ack + manual resolution,
pre-write owner loss/cancel, owner/DB/worker denial, worker outage/stop lifecycle.
Existing12 expiry regressions rerun. Real SQL with simulated Telegram, not live proof.
Command inventory245 names; missing tagging family still explicitly absent.

## Opt-in tagging settings/statistics foundation

Added genuine /allsettings [on|off] and /tagstats in existing group/admin.py.
Current personal Manage chat admin required before write/read and before disclosure,
no bot/anonymous/configured-Owner bypass. Rich simple count/state card and real
Join mentions/Leave mentions buttons. Callback always acts on pressing person's own
ID, group-bound, personal nonbot and current membership checked twice for joining.
Withdrawal allowed even after leaving group, no administrator can enroll another user.
No member roster scraping, inferred consent, presence/online/activity claims or name
storage. Admin output is aggregate count, no consent roster export.

Dedicated tenant/group canonical SQL settings and consent table; serialized group
operations, idempotent join/leave, max500 members, disable atomically clears all
consent so reenabling never restores old opt-ins. Last configuration actor/time kept.
PostgreSQL required; errors redact provider content, no local fallback/retries/fake
success. Late authority loss after write reports saved/details withheld. Member can
race leave/rejoin Telegram across checks; future send worker must revalidate consent
and current membership immediately before sending. No message sends in this phase.

Existing requested /tagall,/all,/etagall,/eall,/tagabort still unregistered until
bounded rate-limited runs and working stop/resume controls exist. UI explicitly says
sending unavailable. This is real settings/consent/stats, not mass-tag completion.
Four realPG tests (initial3 failed before implementation) cover scope/concurrent join/
disable-reenable-reset/leave/500 cap/disable race, current authority/member controls,
and DB-down/invalid personal IDs. No production/live Telegram/deployment/merge.

## /tagall, /all and /tagabort: bounded manual mention runs

Existing admin.py now registers real tagall/all alias and tagabort, backed by existing
group_tagging store extended with durable runs. Personal current Manage chat admin,
group-bound validated UUID Resume/Stop controls, reauthorized immediately before send.
No arbitrary message text or scraped roster: snapshot of1–500 opted-in member IDs,
manual5-member snapshot slices, group-wide30s minimum between claimed batches across
runs. Commands take no extra arguments. First batch sent by command, further batches
require Resume. No background loop/resume-on-restart or promise all users are notified.

SQL group lock and single unresolved run admission; cursor advances durably before
Telegram send, sending state cannot be replayed. Final current membership and fresh
SQL consent/enable/run check; bounded current membership lookups. Confirm only positive
message ID acknowledgement. Failed/timeout/permission-loss state becomes review;
crash may retain sending, both block another batch/run until explicit Stop/tagabort.
No retry of uncertain batch. Completed/stopped snapshots cleared; consent withdrawal
replaces stored snapshot identity with0 sentinel without shifting cursors; disabling
clears all runs' snapshots and stops them. Run metadata retained; no display-name or
message-content storage. Current /tagstats remains aggregate opt-in count, not online
or delivery statistics. Users joining mid-run need a subsequent new run.

Stop cannot recall an already in-flight Telegram request. Consent/member changes can
race the final check and Telegram send (not atomic); UI states limitation. A claimed
slice may produce fewer/zero actual mentions due to leave/withdrawal. Controls show
scanned snapshot progress separately from acknowledged recipient count. Rate-limited
first batch retains Resume/Stop controls so it isn't stranded. /etagall and /eall
remain missing; no fake emoji aliases. No admin commands send to unconsenting users.

Five test-first cases added (initial2 missing store methods failed; new command then
failed KeyError before registration). RealPG concurrent claim/cooldown/withdrawal/
wrong-group/failed-state replay/disable scrub plus simulated Telegram sends, Stop,
timeout redaction and final permission loss. No production/live Telegram/deployment.

## Literal @all/@eall and emoji variants

Existing shared parser now recognizes literal @all and @eall text triggers, only
for their registered all/eall handlers. Not a global ninth prefix: @ban/@tagall,
@alligator, @@all, embedded text and @all@otherbot are not commands. Case-insensitive
exact word boundary; command args remain subject to same no-extra validation. Eight
original punctuation prefixes preserved. command_name marks these two aliases for
passive watchers/cleanup to avoid consuming a recognized command as ordinary chat.
Scope and plugin/admin gates unchanged; ordinary @all is not a Telegram built-in
mention-everyone feature. Delivery depends on Telegram sending this bot the group
message (privacy/admin visibility settings); sandbox filter tests aren't live proof.

/etagall and /eall are genuine shared emoji-style run commands; /all and /tagall
stay plain. Unicode emoji link labels point to the opted-in user IDs, not inferred
random members. Persisted constrained style column with additive default-plain
upgrade preserves existing runs; claim/Resume read style from SQL, never callback
text. Same5-member/manual/30s limit, same current admin/member/consent and stop rules.
No automatic loops or unbounded group scans. No duplication of consent or dispatch
logic. All originally named gaps now declared, but upstream feature parity remains
explicitly incomplete and untouched command UI isn't marked reviewed.

Two regressions: exact/specific @ trigger parsing+negative cases (initial failure),
emoji actual send with realPG style persistence (added parameter) using simulated
Telegram; existing claim race test also asserts persisted emoji style. Full suite
counts in CODEBASE_AUDIT. No deployment/merge/live Telegram/production calls.

## Antiflood command family in-place review

Existing antiflood.py handles flood/setflood/setfloodtimer/floodmode/clearflood with
strict locally validated grammar and current personal Manage chat authority. Bot/
anonymous/invalid IDs refused; no configured Owner bypass. Recheck before changes
and before disclosure, saved state explicitly distinguished from read-only state.
Provider ValueError/other unexpected failures no longer displayed as raw local input
errors. Safe #Errors type-only logs, no retries, committed changes stay saved if
subsequent delivery/rights fail. Backend PolicyError text remains safe authored input/
storage status. Canonical policy/audit/watcher/counters unchanged.

Simpler Off limits, combined count/window, readable action durations, moderator and
Saved/Current saved settings. Independent /antispam burst limiter shown with its own
action so all limits Off does not falsely imply every flood protection is disabled.
Consecutive/timed action separately labelled. Short examples, explicit counters
reset on restart and watcher/permission dependency; not live enforcement proof.

Three test-first regressions added (initial2 failed), final pre-write/read authority,
safe provider ValueError redaction, readable saved state/duration, bot/invalid grammar
no mutations. Existing realPG policy concurrency/tenant/audit rollback and watcher
cases rerun. No new module/command aliases, paused language work remains excluded.

## Tagging always available: group switch removed (supersedes on/off setup)

User requested no enable/disable prerequisite. Enrollment, start, claim and final
eligible checks no longer consult legacy enabled bits. /allsettings is read-only
mention info plus existing personal Join/Leave buttons; no on/off settings writes,
no implicit membership deletion. Retired on/off arguments return short always-
available guidance and do not change consent/run state. Fresh groups can enroll
immediately, existing disabled rows cannot block them. Legacy columns retained and
ignored (no destructive migration); previously deleted consent is NOT resurrected.
A fresh run still requires opted-in members; empty-list guidance points to Join/Leave,
not enabling. Group controls no longer return an enabled flag in internal API.

Personal consent, current administrator checks, final current membership/consent,
500-person snapshot cap,5-member manual batches/group30s limit and Stop/tagabort
remain unchanged. Stop stops a run, not the group's feature. No roster scraping or
automatic enrollment of previously nonconsenting members. Existing10 realPG tagging
cases updated test-first (9 initially failed); disabled legacy bit, fresh use,
concurrent withdrawal/cap/scope, retired off preserving consent, run cancellation,
send acknowledgement/replay/permissions and persisted emoji style covered. No
production/live Telegram/deployment/merge. Interrupted /cleanservice phase retained
but excluded from this commit, along with paused localization/unrelated work.

## /cleanservice settings in-place review

Existing cleaning.py handler now enforces bounded personal nonbot identity, current
Delete messages authority before read/write and after completion before disclosure.
No anonymous/configured Owner bypass. Strict enable/disable aliases preserved; typed
selection replaces previous selection, not an additive toggle. Unknown types or
on/off mixed with extras rejected before store call. Saved vs current saved status,
moderator, readable notice labels, short command examples. No new handlers/buttons/
modules. User help explicitly states replacement semantics and pins stay pinned.

Canonical service_cleaning SQL config/revision audit and service-event watcher are
unchanged. Ordinary content, payments/migrations/topics remain unselected. No pin
state mutation. Requires bot rights for actual notice deletion; saved settings not
live deletion proof. Late rights/delivery failure after successful mutation identifies
saved state; unexpected provider bodies redacted/type-only #Errors/no auto retries.
Local-file audit errors after mutation can be unconfirmed; inspect settings before
retry. Configured PostgreSQL never falls back to local state.

Four regressions (initial three failed before implementation): pre-write/post-read rights loss,
simple saved status/readable labels, provider ValueError redaction, bot/invalid-extra
no mutation. Existing realPG config sharing/group+tenant/audit rollback and watcher
failure/allowlist cases rerun. No live Telegram/production/deployment/merge.

Additional committed-write test covers final rights loss and standalone audit failure without a false rollback claim.
