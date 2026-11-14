# Uptime, Telegram commands and always-on hosting

## What is measured

`/uptime` reports process uptime, Telegram probe state, age of the last success
and successful/failed probe counts. Its clock is monotonic. A restart resets the
clock; this is not a historical availability percentage and does not prove
24/7 service. `/alive` and `/status` remain detailed live screens.

For a web service, `/alive` returns secret-free JSON and `/health/live` answers
process liveness. `/health/ready` returns 200 only for healthy Telegram probes.
The watchdog probes Telegram and asks the hosting supervisor to restart the
process after persistent failures; it does not fake health by calling itself.

## What the inspected references do

- `refs/Videl0/videl/__main__.py` contains a keep-alive thread sending an HTTP
  request to the public `/health` route every **300 seconds**. It tracks success
  and failure counters. The provided Blueprint requests a free web service.
- `refs/Videl1/keep_alive.py` exposes threaded HTTP status and a stale-heartbeat
  check; `__main__.py` refreshes that heartbeat every **20 seconds**. A Blueprint
  comment claims self-pinging, but this helper itself is not an outbound pinger.

A source file, configuration comment or displayed uptime is not evidence of a
service's actual hosting plan or historical 24/7 availability. A stopped/suspended
process cannot keep running its own timer. External checks can observe or wake
some services, depending on host policy; they cannot guarantee uninterrupted
voice playback, polling or assistant connections on a sleeping service.

## Recommended Agent deployment

Agent's existing `render.yaml` uses `type: worker`, `plan: starter`, one long-lived
polling process, and PostgreSQL with `DB_REQUIRED=1`. Apply that Blueprint or
configure an equivalent **always-on paid service** in Render. Merely pushing
these files does not change an existing service's type, plan or billing.

For an existing paid web service instead:

1. Keep the required bot/API/database credentials and `TOKEN_KEY` in the service
   environment. Never paste them into a URL or monitoring service.
2. Let Render supply `PORT`. Agent binds to `0.0.0.0` and exposes HTTP before
   waiting for the previous instance's lease during a rolling deployment.
3. Use `/health/live` for the platform startup/liveness check. Using readiness
   there can recycle the replacement while it is waiting for the old lease.
4. Use `/health/ready` with an external monitor for Telegram-readiness alerts;
   allow a startup grace period. Do not interpret an HTTP root response alone
   as proof that Telegram is connected.
5. Keep one deployment instance per bot token. Never delete another process's
   lease to force a handover. Check Render restart/redeploy events when uptime
   resets; PostgreSQL state survives, but process-local queues do not.

These changes do not purchase a plan, configure an external monitor, deploy to
Render, or guarantee that a hosting provider never has an outage.

## Telegram command registration

With `SYNC_COMMANDS=1` (the default), Agent publishes active registry commands
after connecting and refreshes them after deployment-wide runtime plugin
changes. Clones publish their own command lists using their own client.
Unavailable plugins with no registered handlers are omitted. Group approval,
activation, membership and owner permissions still apply: a published command
is supported, not a promise that every user can invoke it in every group.

Command scopes come from module manifests: shared controls (`/start`, `/help`,
`/ping`, `/uptime`) appear in groups as well as private chats; group-only tools
do not appear in private lists and private clone/owner setup does not leak into
group lists. Empty lists are sent to clear stale scope registrations. Telegram
limits each list to 100 entries; the full active list remains in `/help`.
Registration calls are timeout-bounded and best-effort; a Telegram API failure
must not stop the bot. `SYNC_COMMANDS=0` opts out of publishing, not executing,
commands; it does not delete previously registered command lists.

### Menu button limitation

Telegram has no API value meaning **hide the Menu button while retaining the
registered slash-command list**. Agent now sends `MenuButtonDefault`, instead
of explicitly forcing `MenuButtonCommands` or installing a web-app button.
Telegram clients may still show their built-in Commands/Menu control. Existing
per-chat overrides or language-specific command lists are not enumerated or
bulk-deleted. No claim is made that the button is completely disabled.
