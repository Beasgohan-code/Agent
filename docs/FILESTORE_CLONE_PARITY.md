# FileStore-clone command parity: Videl1 reference

Reference inspected read-only: `Beasgohan-code/Videl1` main SHA `6a00a55f6ad013c85e14c39a9b06922c1bb6f08c`, `VidelBot/filestore/worker_bot/link_gen.py` and command registrations in `extras.py`. Behaviour reference only, no upstream execution or code copying.

User scope: improve the FileStore plugin's **clone bot**, not rename Linkshare/controller commands. Videl1 `/genlink` prompts an admin for a message, resolves/copies it to an archive, then issues a start link. `/batch` prompts first/last messages. Extras registers smartlink, links, premium administration, autolink/post-channel, index/search/searchmode, analytics/stats/export, broadcast/schedules, requests, buttons, custom help/about and maintenance. Inventory of registrations is not proof those services all work or a license to execute upstream code.

| Feature | Native status / next gate |
|---|---|
| Independent worker Home, Help, About, command copy/search | Existing selected/current-registry surfaces; no controller credits |
| Single archive link `/genlink` | This phase: clone running FileStore without Linkshare exposes `/genlink` instead of `/get`; owner-private prompt accepts one forwarded configured-archive message or its private Telegram link |
| Raw new message/media into archive | Corrected genlink: accepts an Owner’s ordinary copyable message, authorizes before Telegram copy and links the acknowledged archive ID. Ambiguous copies are not retried/deleted automatically; no link is promised on failure |
| Batch/custom batch | Existing native guided archive flows remain; not identical to all upstream options |
| Redemption | Existing scoped PostgreSQL archive tickets and private delivery remain; issued links/files not deleted or reformatted |
| Archive access | Existing saved Owner and current bot/Owner archive-admin checks, protected-content checks and tenant scope retained |
| Combined suites/controller | Unchanged: Linkshare still owns `/genlink`, FileStore keeps legacy `/get`. No dynamic collision or global rename; combined FileStore-specific creation remains a future command-routing gate |
| Premium, verification, group protection | Preserve native policies; upstream premium logic is not imported or used to bypass clone limits |
| Settings/custom help/buttons/start identity | Partial native worker UI only; mutable equivalents not implemented by this phase |
| Autolink/index/search/analytics/export/broadcast/scheduling/requests | Not claimed delivered; require separate tenant-safe services, approval and durable job/storage design |

Conversation is in-memory, owner-private, five-minute expiry, cancel/configuration-change invalidation. Single-message completion clears state before creation to prevent duplicate input replay. Existing canonical archive writer rechecks current permissions at creation; no new table, secret or plaintext fallback. Syntax `get-...` from upstream is not adopted; old native link redemption is unchanged.

This is the first tested FileStore-clone slice, **not complete Videl1 feature parity**. Unsupported items must not be exposed as working controls.

## Expanded reference inventory (read-only)
Reviewed reference files: `worker_bot/engine.py`, `link_gen.py`, `flink_logic.py`, `extras.py`, and `utils/helpers.py`. Parsed all five for literal command registrations; manually traced single-link prompting, get_message_id archive reuse/new copy, and native-ingestion integration. This is **not** an exhaustive audit of every upstream backend/database feature. No upstream code is executed or copied.
- `engine.py`: `/ban`, `/id`, `/ping`, `/start`, `/unban`, `/users`.
- `link_gen.py`: `/batch`, `/custom_batch`, `/flink`, `/genlink`, `/start`.
- `flink_logic.py`: `/flink`, `/start`.
- `extras.py`: `/about`, `/addpremium`, `/analytics`, `/antiflood`, `/autolink`, `/broadcast`, `/delbuttons`, `/delpremium`, `/export`, `/help`, `/index`, `/links`, `/maintenance`, `/plan`, `/premiumusers`, `/request`, `/requestmode`, `/requests`, `/schedules`, `/search`, `/searchmode`, `/setabout`, `/setbuttons`, `/sethelp`, `/setpostchannel`, `/setpremium`, `/settings`, `/smartlink`, `/stats`.

## Corrected single-message generation

The first slice incorrectly limited `/genlink` to existing archive references. Corrected flow: `/genlink` → send/forward a copyable message → check current saved Owner/private origin, database, configured archive channel and both admin memberships → bounded Telegram copy (no file download) → recheck configuration → existing scoped single-message ticket generation, which rechecks archive access. Existing archive forwards/links reuse their message ID. Protected/empty/service input rejects. Sessions are consumed before copy to avoid duplicate-message replay; timeout or ambiguous copy instructs inspection/restart rather than blind retry. A successfully copied message may remain without a link if later persistence/authorization fails; no arbitrary archive deletion. This is in-memory session replay protection, not durable exactly-once ingestion. New-message copy is implemented for single `/genlink`; batch/custom ingestion and broader settings/admin parity remain incomplete.

## Exact-selection custom batches

Specialized FileStore clones now use `/custom_batch` → send/forward individual messages → `/done`. Existing archive references can arrive out of numerical order; new messages use the same authorized bounded copy path as `/genlink`. Up to 50 selected messages, duplicate Telegram-input/message-ID checks, no copy after capacity. On `/done`, the existing native ticket backend stores the ordered explicit `message_ids`, not the first-to-last range. This intentionally improves upon upstream range/recopy mechanics by excluding intervening unrelated posts without copying selected posts again. Existing `/batch` remains first-to-last range and controller/combined-suite custom-batch behavior is unchanged. Explicit command arguments continue using existing native range/IDs parsing.

Sessions are still in-memory, five-minute bounded, owner/channel-bound and canceled before ambiguous network failure can replay; failed copy aborts without publishing a partial batch. A failed/canceled batch may leave already acknowledged archive copies, which are not automatically deleted. `/cancel` now says copies are retained. This does not add durable resume, transactional Telegram copying, album grouping, batch raw-ingestion or mutable settings parity. User-visible collection progress includes the selected count and `/done`/`/cancel` guidance.
