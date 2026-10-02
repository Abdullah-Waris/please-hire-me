#!/usr/bin/env python3
"""Compatibility entrypoint: bounded snapshot discovery into the shared ledger."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from hireme.cli import main
if __name__ == '__main__':
    raise SystemExit(main(['discover','--source','delta',*sys.argv[1:]]))
