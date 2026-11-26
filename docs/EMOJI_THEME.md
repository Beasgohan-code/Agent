# User-supplied custom emoji theme

The shared semantic icon map now selects document IDs from the user's @TgEmojis lists (Vector, @rijif, @Boseh/@NewEmojis and Telegram Android Icons). These are user-supplied identifiers, not a claim of live Telegram lookup or verified pack availability.

Existing semantic names remain stable for callers. Representative mappings:

| Semantic key | Glyph | Document ID |
|---|---|---|
| add | ➕ | 5039891861246838069 |
| support | 💬 | 5040036030414062506 |
| updates | 📣 | 5041888071851705019 |
| crown | 👑 | 5039727497143387500 |
| help | 💡 | 5042264341051605743 |
| download | 📥 | 5877307202888273539 |
| copy | 📄 | 5877301185639091664 |
| wave | 👋 | 5040033797031070992 |
| user | 👤 | 5771887475421090729 |
| trash | 🗑 | 5879896690210639947 |
| gear | ⚙️ | 4904936030232117798 |

Full selected mapping lives in `agent/ui/premium.py`. Speaker, unlock and bot retain previous IDs because no matching glyph was supplied; ID/hash remain Unicode-only rather than inventing an ID. No bulk import of unrelated decorative/adult glyphs. No external emoji-bot contact, token or provider requests.

Converted main welcome, shared legacy home navigation, Help categories/pagination, Back/Menu/Help and profile-copy keyboard builders to Theme.button (native custom icon fields, no tg-emoji markup in button labels). Main five-button destinations/callbacks/styles unchanged. Welcome and Help pass their current Theme through, respecting explicit Theme({}) and feature fallback. FileStore result heading now uses the theme link icon, its Open/Share/Copy controls inherit updated supplied IDs.

Custom icons do not duplicate Unicode label prefixes. Unicode fallback retains callback/URL/copy fields and styles, remains idempotent, and does not mutate the original button. USE_PREMIUM_EMOJI=0 and existing unsupported-feature downgrade remain supported. Some literal text/icons elsewhere remain; this is not a repository-wide claim that every emoji has been migrated. No unsupported Telegram rendering/availability claim.

Tests initially failed on missing add/support/download mappings and theme-aware keyboard arguments. Added three map/actions/fallback cases; updated old tests that assumed wave/trash had no supplied ID while retaining explicit unknown-icon coverage. Offline preview refreshed. No new commands, permission changes, worker/controller credit changes or production calls.

## Security, consent and subscription controls

Verification prompts now use the supplied check icon via Theme.button, keeping member/chat-bound callback and SUCCESS style. Federation recipient Accept/Decline use supplied check/cross icons and SUCCESS/DANGER styles, retaining exact invitation payload and consent flow. Required public-channel Join buttons use supplied add icon and PRIMARY style; existing verified channel-ID/type/username checks and private-channel behavior unchanged.

Verification/federation prompt sends use existing rich.send compatibility wrapper: explicit custom-icon rejection downgrades once with Unicode; ambiguous delivery errors never trigger retry. Prompt failure/recovery and pending verification semantics remain unchanged. No new security permissions, federation actions, source subscriptions or credentials.

Six new tests cover verification callback/style/native and disabled themes, exact federation bindings/styles, explicit icon-rejection fallback without mutation, no retry on ambiguous timeout, and required-channel URL preservation. Initial three cases failed before implementation. Synthetic Telegram controls, not live verification/consent/member access proof.
