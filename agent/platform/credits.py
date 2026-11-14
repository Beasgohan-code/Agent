"""Agent — where the ideas in this bot come from.

Every plugin in this repository was written for it; none of it is a copy-paste
of the projects below. What they gave is the part that is hard to invent: which
commands a Telegram file-store bot is expected to answer, what the sensible
defaults are, and how their panels are laid out. Naming them is the point of
this module — a bot that quietly re-implements someone's command surface and
says nothing about it is a worse bot.

The licence column is the upstream licence as it stands in its repository,
because it decides what *could* be reused rather than just what was read:

* **MIT** — reusable with attribution;
* **AGPL-3.0** — network copyleft: reusing code would put this whole bot under
  it, so those projects were read for behaviour only;
* **no licence file** — all rights reserved: read, not reused;
* **Attribution & personal use** — Playeon's own licence, which is why its
  layout informed the music panel and nothing of its code is here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Credit:
    """One upstream project."""

    name: str
    url: str
    author: str
    licence: str
    contribution: str

    @property
    def line(self) -> str:
        return f"{self.name} — {self.contribution} ({self.licence})"


CREDITS: tuple[Credit, ...] = (
    Credit(
        "Meikoagent",
        "https://github.com/Beasgohan-code/Meikoagent",
        "Beasgohan-code",
        "no licence file",
        "the built-in plugin set: filestore, leech, music, reports, post maker, security",
    ),
    Credit(
        "Videl0",
        "https://github.com/Beasgohan-code/Videl0",
        "Beasgohan-code",
        "no licence file",
        "queue and music command vocabulary",
    ),
    Credit(
        "Videl1",
        "https://github.com/Beasgohan-code/Videl1",
        "Beasgohan-code",
        "no licence file",
        "keep-alive, graceful restart and plugin switching",
    ),
    Credit(
        "CBML",
        "https://github.com/abhinai2244/CBML",
        "abhinai2244",
        "AGPL-3.0",
        "leech and mirror task commands",
    ),
    Credit(
        "WZML-X",
        "https://github.com/SilentDemonSD/WZML-X",
        "SilentDemonSD",
        "AGPL-3.0",
        "transfer status layout",
    ),
    Credit(
        "Multi-FileStoreBot",
        "https://github.com/abhinai2244/Multi-FileStoreBot",
        "abhinai2244",
        "no licence file",
        "file-store commands and quotas",
    ),
    Credit(
        "LINK-SHAREBOT",
        "https://github.com/abhinai2244/LINK-SHAREBOT",
        "abhinai2244",
        "no licence file",
        "link protection commands",
    ),
    Credit(
        "ENCODING-BOT",
        "https://github.com/abhinai2244/ENCODING-BOT",
        "abhinai2244",
        "AGPL-3.0",
        "encoding command surface and presets",
    ),
    Credit(
        "save-restricted-content-bot",
        "https://github.com/abhinai2244/save-restricted-content-bot",
        "LastPerson07",
        "MIT",
        "saving protected media",
    ),
    Credit(
        "Playeon",
        "https://github.com/playeon/Playeon",
        "Sushi",
        "Attribution & personal use",
        "music panel layout",
    ),
    Credit(
        "richgram",
        "https://github.com/Badmunda05/richgram",
        "Badmunda05",
        "MIT",
        "the rich layer this UI is built on",
    ),
    Credit(
        "wzgram",
        "https://github.com/rjriajul/wzgram",
        "rjriajul",
        "LGPL-3.0",
        "the Telegram client",
    ),
)

#: What this line means, said once so no panel has to repeat it.
NOTICE = (
    "Written for this bot, not copied: these projects were read for command "
    "names, defaults and layout."
)


def rows() -> list[tuple[str, str]]:
    """Two-column rows for a credit table: project, then what it gave."""
    return [(credit.name, credit.contribution) for credit in CREDITS]


def by_name(name: str) -> Credit | None:
    lowered = (name or "").strip().lower()
    return next((c for c in CREDITS if c.name.lower() == lowered), None)
