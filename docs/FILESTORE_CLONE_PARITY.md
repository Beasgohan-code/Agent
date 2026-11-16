# FileStore-clone command parity: Videl1 reference

Reference inspected read-only: `Beasgohan-code/Videl1` main SHA `6a00a55f6ad013c85e14c39a9b06922c1bb6f08c`, `VidelBot/filestore/worker_bot/link_gen.py` and command registrations in `extras.py`. Behaviour reference only, no upstream execution or code copying.

User scope: improve the FileStore plugin's **clone bot**, not rename Linkshare/controller commands. Videl1 `/genlink` prompts an admin for a message, resolves/copies it to an archive, then issues a start link. `/batch` prompts first/last messages. Extras registers smartlink, links, premium administration, autolink/post-channel, index/search/searchmode, analytics/stats/export, broadcast/schedules, requests, buttons, custom help/about and maintenance. Inventory of registrations is not proof those services all work or a license to execute upstream code.

| Feature | Native status / next gate |
|---|---|
| Independent worker Home, Help, About, command copy/search | Existing selected/current-registry surfaces; no controller credits |
| Single archive link `/genlink` | This phase: clone running FileStore without Linkshare exposes `/genlink` instead of `/get`; owner-private prompt accepts one forwarded configured-archive message or its private Telegram link |
| Raw new message/media into archive | Not delivered here; needs pre-copy admin/channel authorization, bounded copy acknowledgement and owned failure cleanup |
| Batch/custom batch | Existing native guided archive flows remain; not identical to all upstream options |
| Redemption | Existing scoped PostgreSQL archive tickets and private delivery remain; issued links/files not deleted or reformatted |
| Archive access | Existing saved Owner and current bot/Owner archive-admin checks, protected-content checks and tenant scope retained |
| Combined suites/controller | Unchanged: Linkshare still owns `/genlink`, FileStore keeps legacy `/get`. No dynamic collision or global rename; combined FileStore-specific creation remains a future command-routing gate |
| Premium, verification, group protection | Preserve native policies; upstream premium logic is not imported or used to bypass clone limits |
| Settings/custom help/buttons/start identity | Partial native worker UI only; mutable equivalents not implemented by this phase |
| Autolink/index/search/analytics/export/broadcast/scheduling/requests | Not claimed delivered; require separate tenant-safe services, approval and durable job/storage design |

Conversation is in-memory, owner-private, five-minute expiry, cancel/configuration-change invalidation. Single-message completion clears state before creation to prevent duplicate input replay. Existing canonical archive writer rechecks current permissions at creation; no new table, secret or plaintext fallback. Syntax `get-...` from upstream is not adopted; old native link redemption is unchanged.

This is the first tested FileStore-clone slice, **not complete Videl1 feature parity**. Unsupported items must not be exposed as working controls.
