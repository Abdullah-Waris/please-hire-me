#!/usr/bin/env python3
"""Retired: application verification is a human exception in the dedicated browser.

No Keychain/Gmail/clipboard access is performed. A future OTP integration must use
an application-bound credential service, not a callable secret-reading module.
"""
if __name__ == '__main__':
    raise SystemExit('Legacy Gmail broker disabled. Complete verification through the dashboard job link.')
