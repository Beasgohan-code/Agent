# UI preview

Offline render of the real screen builders with a deliberately small command fixture. This is not a Telegram screenshot, a live health check, or a deployment-wide command count. Actual screens use the live registered catalogue plus `/start`, `/help`, and `/ping`.

Regenerate from the repository root with `.venv/bin/python -m tools.render_ui_preview`. The tool makes no network or storage calls. Native rich messages remain the primary UI; the text below is produced from the existing classic fallback renderer.

Fixture commands: `/ask`, `/autochat`, `/custom_batch`, `/get`, `/gu`, `/help`, `/ping`, `/plugins`, `/start`.

## /start

```text
💎 Meiko

Your group. Your workspace.
👋 Hello, Gohan!
🛡 Keep your community protected. Bring music, media and useful tools into one focused workspace.
Version  0.1.0
Core  Moderation · always available
Commands  9

Workspace
Feature  Commands
Encoder  Not registered
Moderation  Not registered
Post maker  Not registered
Music  Not registered
Linkshare  Not registered
FileStore  2 registered
Leech  Not registered
AI Agent  2 registered

Try your next action
• /help — Browse your command library
• /plugins — Open plugin controls for this chat

─────
Prefixes: / ! . # $ % & ? · Registration is not group activation. Optional plugins need Owner approval and group-admin activation.
```

Buttons (row order):
- 💡 Help · 💬 Support
- 📣 Updates · 👑 Owner

## /help

```text
✨ Help

What would you like to do?
Choose a category, then tap a command for its details.
All commands accept / ! . # $ % & ? — for example, !help, .play, ?settings. Permissions and plugin availability still apply.

Section  Commands
✨ AI Agent  2
⚡ Essentials  4
📦 Vault & downloads  2
🤖 Operations (owner)  1

─────

Tap a category below · /help play finds a command directly.
```

Buttons (row order):
- ✨ AI Agent · ⚡ Essentials
- 📦 Vault & downloads · 🤖 Operations (owner)
- ⬅️ Back to menu

## /help essentials

```text
⚡ Essentials

Your everyday shortcuts. Start here, check your status or get help.

Command  What it does
/start  Open the main menu
/help  Every command, one screen per section
/ping  Health and latency of this instance
/gu  Live card demo; /gu fail previews failure (group admin)

─────

Page 1 of 1 · Tap a command below for details · All commands accept / ! . # $ % & ? · Choose another category or return to your workspace.
```

Buttons (row order):
- 💡 /start · 💡 /help
- 💡 /ping · 💡 /gu
- 📁 All sections
- ⬅️ Back to menu

## /help autochat

```text
/autochat

Command  /autochat
What it does  Opt-in private chat and group mention/reply AI mode
Section  AI Agent
Registered here  yes — permissions and activation still apply

Tap AI Agent for the rest of its commands.

─────
💡 Viewing help does not run a command or grant permissions. /help lists every section.
```

Buttons (row order):
- ⬅️ Back to AI Agent
- 📁 All sections · 🏡 Menu

## Encoder clone · /help encode (encode-only fixture)

```text
⚙️ /encode

Command details
Detail  Information
/encode  Encode a replied video
How to use  /encode balanced
Before sending  Reply to a supported video or document. Choose fast, balanced or quality; the original is not modified.
Registered here  Yes · registration does not prove activation or permission
Tool  Encoder
Chat scope  private
Permissions  messages.read, files.write, process.spawn
Dependencies  None declared
Required credential names  None declared
Required capabilities  None declared

Declared requirements are not a readiness check or access grant. Group tools may require Owner approval, admin activation and Telegram rights. Copying does not run this command; add required arguments before sending.

─────

Send the command for its current usage. Never include passwords or secret tokens.
```

Buttons (row order):
- 📌 Copy /encode
- ⬅️ Back to commands · ⚡ Get started
- 🤖 Home · 🔍 All tools

## FileStore clone · /help genlink (archive-only fixture)

```text
🔒 /genlink

Command details
Detail  Information
/genlink  Create a single-message archive delivery link (Owner, private chat).
How to use  /genlink
Before sending  Send the command without arguments in private chat as this bot’s Owner, then send or forward one message. Follow any access/configuration checks shown.
Registered here  Yes · registration does not prove activation or permission
Tool  FileStore
Chat scope  all
Permissions  messages.read, messages.send, storage.read, storage.write
Dependencies  None declared
Required credential names  None declared
Required capabilities  None declared

Declared requirements are not a readiness check or access grant. Group tools may require Owner approval, admin activation and Telegram rights. Copying does not run this command; add required arguments before sending.

─────

Send the command for its current usage. Never include passwords or secret tokens.
```

Buttons (row order):
- 📌 Copy /genlink
- ⬅️ Back to commands · ⚡ Get started
- 🤖 Home · 🔍 All tools

## Runtime behavior

- The Telegram menu is capped at 100 commands. Overflow prioritizes cross-feature entry points; Help retains the active catalogue. Registration does not prove group approval or health.

- Menu delivery follows the command scope and supported recipient-only group navigation; this offline render does not verify Telegram delivery. Group plugin controls retain Owner approval, admin activation and the three-optional-plugin limit; moderation is slot-free.

- AI requires a configured key and model. `/ask` sends an explicit question. `/autochat on|off|status` controls default-off private text replies or group mention/reply triggers. Group configuration requires an administrator. Only the triggering text is sent to the external provider, without chat history; charges may apply.

- FileStore clones use `/genlink`, `/batch`, and `/custom_batch`; the controller retains `/get`. Retired `/check` and vault commands `/fsave`, `/files`, and `/del` are not restored.

- Provider, music, FileStore transfer and control-panel actions are not exercised by this preview. Verify them separately; no online, latency or deployment claim is implied.
