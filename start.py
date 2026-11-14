"""Agent — entry point.

Usage:
    python start.py            # run the bot (long polling)
    python start.py --check    # validate configuration and wiring, then exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import replace

from dotenv import load_dotenv

from agent.bot import AgentBot
from agent.config import ConfigError, Settings
from agent.logging_setup import configure_logging
from agent.platform.paths import resolve_data_dir

logger = logging.getLogger("agent")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="start.py", description="Agent — Telegram bot")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and handler wiring, then exit without connecting",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    load_dotenv()
    configure_logging()

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logger.critical("%s", exc)
        return 2

    # Token is masked and the api_id is not a credential — but it is also not
    # something a public build log needs, so it is not printed at all.
    logger.info("Configuration loaded (token=%s)", settings.masked_token)

    # Resolve a writable data directory once, before anything tries to write.
    # Settings is frozen, so the resolved path replaces it rather than mutating.
    data_dir, preferred_ok = resolve_data_dir(settings.data_dir)
    if not preferred_ok:
        logger.warning(
            "Running with %s instead of %s; stored data is ephemeral until the "
            "volume is writable.",
            data_dir,
            settings.data_dir,
        )
    settings = replace(settings, data_dir=data_dir)

    bot = AgentBot(settings)

    if args.check:
        try:
            bot.build()
        except Exception:
            logger.exception("Preflight check failed.")
            return 1
        logger.info(
            "Preflight OK: client initialised, %d handlers registered. Not connecting.",
            bot.handler_count,
        )
        return 0

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Interrupted; exiting.")
        return 0
    except Exception:
        logger.exception("Agent stopped because of an unhandled error.")
        return 1

    if bot.fatal_reason:
        logger.error(
            "Exiting with code 1 so the platform restarts the container (%s).",
            bot.fatal_reason,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
