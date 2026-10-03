from __future__ import annotations
import shutil
import sys
import platform
from pathlib import Path
from .connections import status


def readiness(store,verify=False):
    s=store.settings();channel=s['browser_channel']
    if channel=='system-chromium':browser=bool(shutil.which('chromium') or shutil.which('chromium-browser'))
    elif channel=='chrome':browser=bool(shutil.which('google-chrome') or shutil.which('chrome') or Path('/Applications/Google Chrome.app').exists())
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:browser=Path(p.chromium.executable_path).is_file()
    provider=status(store,verify)
    return {'platform':sys.platform,'architecture':platform.machine(),'python':platform.python_version(),'browser_ready':browser,'provider':provider,'missing':store.missing_setup(),'deployment':s['deployment'],'supported_platform':sys.platform in ('darwin','linux')}
