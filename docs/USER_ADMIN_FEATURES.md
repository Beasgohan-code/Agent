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
