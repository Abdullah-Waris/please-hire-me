"""Private credentials and durable intent for future employer account adapters.

This module performs no network actions. Passwords never enter the ledger,
events, model context, dashboard snapshots, or portable backups.
"""
from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

from .util import Blocked, atomic_json, digest, now, private_dir


def account_key(origin, company):
    p = urlsplit(origin)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None, 443) or p.path not in ('', '/') or p.query or p.fragment):
        raise ValueError('An exact HTTPS account origin is required')
    if not isinstance(company, str) or not company.strip():
        raise ValueError('An employer account scope is required')
    return digest([p.hostname.lower(), company.strip().casefold()])


class AccountVault:
    def __init__(self, store):
        self.store = store
        self.directory = private_dir(store.root / 'integrations' / 'accounts')

    def credentials(self, origin, company, *, create=False):
        key = account_key(origin, company)
        path = self.directory / (key + '.json')
        if path.is_symlink():
            raise Blocked('account_credentials_unavailable')
        email = self.store.facts().get('email', {}).get('value')
        if not email:
            raise Blocked('account_identity_unconfirmed')
        if path.exists():
            try:
                if not path.is_file() or path.stat().st_size > 4096:
                    raise ValueError('Invalid credential file')
                value = json.loads(path.read_text())
                valid = (isinstance(value, dict) and value.get('email') == email
                         and isinstance(value.get('password'), str)
                         and 20 <= len(value['password']) <= 128)
            except (OSError, ValueError):
                valid = False
            if not valid:
                raise Blocked('account_credentials_unavailable')
            return value
        if not create:
            raise Blocked('account_credentials_unavailable')
        # A restored ledger must not silently generate a different password.
        if self.store.db.execute('SELECT 1 FROM employer_accounts WHERE id=?', (key,)).fetchone():
            raise Blocked('account_credentials_unavailable')
        value = {'email': email, 'password': 'Aa1!' + secrets.token_urlsafe(24)}
        atomic_json(path, value)
        return value

    def begin_creation(self, origin, company):
        """Commit intent before an adapter may send an account-creation POST."""
        key = account_key(origin, company)
        self.credentials(origin, company)
        with self.store.transaction():
            self.store.checkpoint()
            if self.store.db.execute('SELECT 1 FROM employer_accounts WHERE id=?', (key,)).fetchone():
                raise Blocked('account_creation_held')
            self.store.db.execute('INSERT INTO employer_accounts VALUES(?,?,?,?,?)',
                                  (key, origin, company, 'creating', now()))
            self.store.event('account_creation_intent', key, {})
        return key

    def finish_creation(self, key, *, confirmed):
        if not isinstance(confirmed, bool):
            raise ValueError('An explicit account confirmation is required')
        with self.store.transaction():
            row = self.store.db.execute('SELECT state FROM employer_accounts WHERE id=?', (key,)).fetchone()
            if not row or row['state'] != 'creating':
                raise Blocked('account_creation_held')
            state = 'confirmed' if confirmed else 'uncertain'
            self.store.db.execute('UPDATE employer_accounts SET state=?,updated=? WHERE id=?', (state, now(), key))
            self.store.event('account_creation_result', key, {'state': state})
