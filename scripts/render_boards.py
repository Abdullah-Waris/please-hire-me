#!/usr/bin/env python3
"""Print the current ledger's source health; never overwrite tracked research from remote data."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from hireme.store import Store
from hireme.cli import DEFAULT_ROOT

if __name__=='__main__':
    store=Store(DEFAULT_ROOT)
    try:
        for row in store.db.execute('SELECT id,status,checked,error FROM sources ORDER BY id'):
            print(json.dumps(dict(row)))
    finally:store.close()
