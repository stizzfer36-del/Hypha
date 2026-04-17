"""M1 — ledger tests.

Covers:
  - schema creation idempotent
  - append -> recent round-trip
  - kind filter
  - persistence across reconnect (WAL)
"""

import pytest


@pytest.mark.skip(reason="M1 implementation pending")
def test_placeholder() -> None:
    pass
