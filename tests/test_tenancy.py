"""One database, many bots: scoped rows and encrypted clone tokens.

The main bot and every clone connect to the same PostgreSQL database and keep
documents with the same names (``runtime``, ``premium``, ``chats`` …). These
tests pin the two rules that keep that safe: a scope prefix on every row and
lease, and ciphertext for the one credential a clone record holds.
"""

import asyncio
import base64
import json

import pytest

from agent.config import Settings
from agent.modules.clone.store import Clone, CloneStore
from agent.platform.db import Database
from agent.platform.secrets import SecretBox, SecretError, normalise_key

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


# --- scopes ----------------------------------------------------------------


def test_the_main_bot_is_scoped_by_its_own_id():
    settings = Settings.from_env(ENV)

    assert settings.bot_id == 123456789
    assert settings.db_scope == "main:123456789"


def test_every_document_name_carries_its_scope():
    main = Database("postgres://u:p@h/db", scope="main:1")
    clone = Database("postgres://u:p@h/db", scope="clone:2")

    assert main.name_for("runtime") == "main:1:runtime"
    assert clone.name_for("runtime") == "clone:2:runtime"
    assert main.name_for("runtime") != clone.name_for("runtime")
    # Leases are scoped the same way, so two bots never contend for one lease.
    assert main.lease_key("agent") == "main:1:agent"
    assert clone.lease_key("agent") == "clone:2:agent"


def test_a_scope_is_reduced_to_safe_characters():
    assert Database(None, scope="main:1; DROP TABLE").scope == "main:1DROPTABLE"
    assert Database(None, scope="").scope == "global"


class FakeConnection:
    """Just enough of an asyncpg connection to observe what the SQL sees."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append((sql, args))
        return self.rows

    async def execute(self, sql, *args):
        self.queries.append((sql, args))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        return None

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return self.connection


def test_loading_reads_only_this_scopes_rows():
    rows = [
        {"name": "main:1:runtime", "value": json.dumps({"disabled": ["a"]})},
        {"name": "clone:2:runtime", "value": json.dumps({"disabled": ["b"]})},
    ]
    connection = FakeConnection(rows)
    db = Database("postgres://u:p@h/db", scope="main:1")
    db._pool = FakePool(connection)
    db.connected = True

    loaded = asyncio.run(db.load())

    assert loaded == 1
    # The store sees the plain name it has always used.
    assert db.get("runtime") == {"disabled": ["a"]}
    assert "clone:2:runtime" not in db._docs


def test_a_write_is_stored_under_its_scoped_name():
    connection = FakeConnection()
    db = Database("postgres://u:p@h/db", scope="clone:2")
    db._pool = FakePool(connection)
    db.connected = True

    asyncio.run(db._write_batch({"premium": {"x": 1}}))

    sql, args = connection.queries[0]
    assert args[0] == "clone:2:premium"
    assert json.loads(args[1]) == {"x": 1}


def test_a_lease_is_taken_under_its_scoped_name():
    connection = FakeConnection()
    db = Database("postgres://u:p@h/db", scope="main:1")
    db._pool = FakePool(connection)
    db.connected = True

    asyncio.run(db.take_lease("agent", "host", 30.0))

    assert connection.queries[0][1][0] == "main:1:agent"


# --- token encryption ------------------------------------------------------


def a_key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode()


def test_a_key_can_be_a_fernet_key_or_hex():
    fernet = normalise_key(a_key())
    hexed = normalise_key("ab" * 32)

    assert len(base64.urlsafe_b64decode(fernet)) == 32
    assert len(base64.urlsafe_b64decode(hexed)) == 32


def test_a_bad_key_says_how_to_make_one():
    with pytest.raises(SecretError) as error:
        normalise_key("too-short")

    assert "Fernet.generate_key" in str(error.value)


def test_a_value_round_trips_and_never_looks_like_itself():
    box = SecretBox(a_key())

    sealed = box.encrypt("123456789:SECRET-TOKEN-VALUE")

    assert sealed.startswith("v1:")
    assert "SECRET" not in sealed
    assert box.decrypt(sealed) == "123456789:SECRET-TOKEN-VALUE"


def test_a_different_key_cannot_read_it():
    sealed = SecretBox(a_key()).encrypt("token")

    with pytest.raises(SecretError):
        SecretBox(base64.urlsafe_b64encode(b"z" * 32).decode()).decrypt(sealed)


def test_no_key_keeps_plaintext_and_says_so(caplog):
    box = SecretBox(None)

    assert box.enabled is False
    assert box.encrypt("token") == "token"
    assert box.decrypt("token") == "token"


def test_a_key_without_the_library_is_an_error(monkeypatch):
    """Never silently downgrade: a key that cannot encrypt must refuse."""
    import agent.platform.secrets as secrets

    monkeypatch.setattr(secrets, "_fernet_module", lambda: None)
    with pytest.raises(SecretError):
        SecretBox(a_key())


# --- the clone store -------------------------------------------------------


def test_a_clone_token_is_written_as_ciphertext(tmp_path):
    store = CloneStore(tmp_path, box=SecretBox(a_key()))
    store.add(Clone(bot_id=1, owner_id=7, token="123:AAsecret"))

    raw = (tmp_path / "clones.json").read_text()

    assert "AAsecret" not in raw
    assert "token_enc" in raw
    assert store.get(1).token == "123:AAsecret"          # decrypted in memory


def test_a_plaintext_record_is_migrated_and_rewritten(tmp_path):
    (tmp_path / "clones.json").write_text(
        json.dumps([{"bot_id": 1, "owner_id": 7, "token": "123:AAlegacy"}])
    )

    store = CloneStore(tmp_path, box=SecretBox(a_key()))

    assert store.get(1).token == "123:AAlegacy"
    raw = (tmp_path / "clones.json").read_text()
    assert "AAlegacy" not in raw                          # rewritten encrypted
    assert "token_enc" in raw


def test_a_record_this_key_cannot_read_is_skipped_not_crashed(tmp_path):
    other = SecretBox(base64.urlsafe_b64encode(b"z" * 32).decode())
    (tmp_path / "clones.json").write_text(
        json.dumps([{"bot_id": 1, "owner_id": 7, "token_enc": other.encrypt("123:AAx")}])
    )

    store = CloneStore(tmp_path, box=SecretBox(a_key()))

    assert store.count() == 0


def test_without_a_key_the_store_still_works_in_plaintext(tmp_path):
    store = CloneStore(tmp_path, box=SecretBox(None))
    store.add(Clone(bot_id=1, owner_id=7, token="123:AAplain"))

    raw = (tmp_path / "clones.json").read_text()

    assert "AAplain" in raw
    assert store.encrypted() is False


def test_a_clone_runs_in_its_own_database_scope(tmp_path):
    from agent.modules.clone.manager import CloneManager

    settings = Settings.from_env({**ENV, "DATABASE_URL": "postgres://u:p@h/db"})
    manager = CloneManager(settings, CloneStore(tmp_path, box=SecretBox(None)))

    clone_settings = manager.settings_for(Clone(bot_id=99, owner_id=1, token="99:AAx"))

    assert clone_settings.db_scope == "clone:99"
    assert clone_settings.bot_token == "99:AAx"
    assert clone_settings.owner_id is None
