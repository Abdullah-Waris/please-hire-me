#!/usr/bin/env python3
"""Extract explicitly wikilinked companies from a user-selected tracker file."""
import re
import sys
from pathlib import Path

def names(text):
    return list(dict.fromkeys(m.group(1).strip() for m in re.finditer(r'\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]',text)))

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: tracker_companies.py /absolute/path/to/tracker.md')
    path=Path(sys.argv[1])
    if path.is_symlink() or not path.is_file():raise SystemExit('Tracker must be a readable regular file')
    print('\n'.join(names(path.read_text())))
