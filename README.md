# Agent

A Telegram bot. Phase 1: `/start`, `/help`, user profile, inline keyboards and
callback navigation. Built on **wzgram** (client) and **richgram** (formatting).

## Environment

Only three variables, all required:

| Variable    | Where to get it                              |
| ----------- | -------------------------------------------- |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather)         |
| `API_ID`    | [my.telegram.org](https://my.telegram.org) → API development tools |
| `API_HASH`  | same page as `API_ID`                        |

Nothing else needs to be set. No secrets belong in the repo or the image.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps richgram==0.2.0     # see "richgram" note below

cp .env.example .env                      # then fill in the three values
python start.py                           # long polling
python start.py --check                   # validate config + wiring, no network
```

## Run with Docker

```bash
docker build -t agent .
docker run --rm -e BOT_TOKEN=... -e API_ID=... -e API_HASH=... agent
```

## Deploy on Render

The included `render.yaml` creates a **Background Worker** with
`runtime: docker`, so no HTTP server or keep-alive is involved. Either apply
the Blueprint or create the worker manually:

- Type: **Background Worker**
- Runtime: **Docker** (`./Dockerfile`)
- Start command: `python start.py` (already the image `CMD`)
- Environment: `BOT_TOKEN`, `API_ID`, `API_HASH`

Render sends `SIGTERM` on deploy/restart; the bot turns it into a graceful
disconnect.

## Layout

```
start.py              entry point ("python start.py")
agent/config.py       environment loading + validation
agent/bot.py          client lifecycle, handler wiring, signals
agent/handlers/       commands (/start, /help) and callbacks
agent/ui/             theme, screens, inline keyboards
agent/utils/sender.py delivery with HTML + custom-emoji fallbacks
tests/                config, UI and bot tests
```

## Notes

**richgram is installed with `--no-deps`.** Its only runtime dependency is
`kurigram`, which ships its own top-level `pyrogram` package and overwrites
wzgram's files (observed: `pyrogram.__version__` became `2.2.27`). Installing
it without dependencies lets wzgram own `pyrogram`, and richgram still works
because all it needs is that package.

**richgram was renamed upstream.** `github.com/Badmunda05/richgram` now
redirects to `Badmunda05/nextgram`; `richgram` 0.2.0 on PyPI is the last
release under the old name and is what this project pins. `nextgram` 0.9.0 is
the actively maintained successor — a reasonable migration target later.

**Custom emoji IDs are not shipped.** Inventing one renders a broken glyph.
Add verified IDs to `CUSTOM_EMOJI_IDS` in `agent/ui/theme.py`; until then every
glyph uses its unicode fallback, and a rejection by Telegram is downgraded
automatically.
