#!/usr/bin/env bash
# Retired. A regex is not a secret boundary. The managed worker invokes Claude
# with no tools, no MCP, no browser, and safe mode; it never exposes this hook.
printf 'Legacy secret regex retired; use the tool-free managed worker.\n' >&2
exit 2
