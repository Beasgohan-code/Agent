"""Suite-wide isolation for module-level switches.

Two pieces of UI state are global on purpose — the custom-emoji switch and the
rich/classic table switch — because one Telegram refusal has to change the whole
process, not one message. Tests that trip them must not leak into each other, so
every test starts and ends on the default.
"""

import pytest

from agent.ui import tables


@pytest.fixture(autouse=True)
def _default_rendering():
    tables.set_rich(True)
    yield
    tables.set_rich(True)
