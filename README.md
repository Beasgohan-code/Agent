# Agent

A Telegram bot. Phase 1: `/start`, `/help`, `/ping`, user profile, inline
keyboards and callback navigation. Built on **wzgram** (client) and **richgram** (formatting).

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


## Health & watchdog

Modelled on Videl1's keep-alive and Meikoagent's watchdog, with the parts that
get accounts suspended removed.

**What it does**

- Probes Telegram (`getMe`) on a timer and records latency, failures and the
  last error.
- Derives a state: `starting` → `healthy` / `degraded` / `down`.
  Down = 3 consecutive failures *or* no successful probe for
  `WATCHDOG_INTERVAL_SECONDS × 10`.
- Reconnects a dropped socket before pinging.
- After `WATCHDOG_FATAL_AFTER` (default 5) failed probes it logs a CRITICAL
  line, disconnects cleanly and exits **1** so Docker/Render restarts the
  container. Rebuilding the client in-place is avoided on purpose — two update
  streams would double every reply.

**What it deliberately does *not* do**

- **No self-ping.** Nothing calls the bot's own endpoint to fake traffic. That
  is the practice your hosting terms punish and Videl1's `self_ping_loop` does.
- **No HTTP server by default.** A polling bot on a Background Worker needs
  none. Set `HEALTH_PORT` (or deploy as a web service, where the platform sets
  `PORT`) to expose:

  | Route | Purpose |
  | --- | --- |
  | `GET /health` | JSON state, uptime, latency, failures, version. **503** when down, so the platform's own health check restarts the container |
  | `GET /health/live` | `ok` — process liveness only, so a slow probe never kills a healthy container |
  | `GET /` | one-line banner |

**Checking the ping**

Two ways, depending on the deployment shape:

| Where | How | What you get |
| --- | --- | --- |
| Telegram | send `/ping` | state, uptime, Telegram latency, probe/failure counts, last update, last error |
| HTTP | `curl https://<service>/health` | the same numbers as JSON (needs `HEALTH_PORT` or a web service) |

`/ping` works on a Background Worker, where no port is exposed — that is the
reason it exists alongside the HTTP endpoint.

**Tuning (all optional)**

```bash
HEALTH_PORT=8080              # 0 = no endpoint
WATCHDOG_INTERVAL_SECONDS=30
WATCHDOG_TIMEOUT_SECONDS=20
WATCHDOG_FATAL_AFTER=5
```

Not implemented yet: Videl1's cross-instance lease (it needs shared storage to
be meaningful — see the no-database rule for this phase).

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
