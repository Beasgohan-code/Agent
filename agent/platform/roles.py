"""Legacy sudo ID storage retained for compatibility, not authorization.

Runtime delegation uses PostgreSQL SudoAccess capabilities. These IDs grant
neither Premium clone eligibility nor Owner/Telegram administrator rights.
"""
from .db import load_document, save_document


class SudoStore:
    def __init__(self, root, *, owner_id=None, db=None):
        self.owner_id = owner_id
        self.db = db
        self.path = root / 'sudo.json'
        raw = load_document(db, 'sudo', self.path, [])
        self._ids = {value for value in raw if type(value) is int and 0 < value < 2**63} if isinstance(raw, list) else set()

    def contains(self, user_id):
        return type(user_id) is int and user_id in self._ids

    def members(self):
        return tuple(sorted(self._ids))

    def change(self, actor_id, user_id, *, add):
        if not self.owner_id or type(actor_id) is not int or actor_id != self.owner_id:
            raise PermissionError('Only the bot Owner may change sudo access.')
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise ValueError('Use a positive Telegram user id.')
        updated = self._ids | {user_id} if add else self._ids - {user_id}
        save_document(self.db, 'sudo', self.path, sorted(updated))
        self._ids = updated
