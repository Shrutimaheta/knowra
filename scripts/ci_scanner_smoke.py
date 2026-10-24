"""Verify a real scanner accepts clean input and rejects the harmless EICAR test."""

import base64
import time

from app.malware import scan
from fastapi import HTTPException

deadline = time.monotonic() + 600
while True:
    try:
        scan(b"Fictional clean document")
        break
    except HTTPException:
        if time.monotonic() >= deadline:
            raise
        time.sleep(5)
# Standard anti-malware test string, never executed or written to a file.
sample = base64.b64decode("WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=")
try:
    scan(sample)
except HTTPException as error:
    assert error.status_code == 400
else:
    raise AssertionError("Scanner did not reject the harmless test signature")
print("Real ClamAV clean-file and harmless test-signature checks passed")
