# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import threading
from datetime import datetime

_lock = threading.Lock()
_counts: dict[str, int] = {}  # "YYYY-MM-DDTHH:bucket" -> count

LIMITS = {
    "analysis": 10,
    "stylize": 5,
}


def _hour_key(bucket: str) -> str:
    return f"{datetime.utcnow().strftime('%Y-%m-%dT%H')}:{bucket}"


def check_and_increment(bucket: str) -> bool:
    """Returns True if the call is allowed, False if the hourly limit is reached."""
    key = _hour_key(bucket)
    limit = LIMITS[bucket]
    with _lock:
        count = _counts.get(key, 0)
        if count >= limit:
            return False
        _counts[key] = count + 1
        return True


def remaining(bucket: str) -> int:
    key = _hour_key(bucket)
    with _lock:
        return max(0, LIMITS[bucket] - _counts.get(key, 0))
