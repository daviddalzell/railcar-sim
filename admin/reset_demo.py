# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Nightly demo reset — re-seeds the public schema with the sample layout.

Can be run directly or via the /admin/reset-demo endpoint.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def reset():
    from dotenv import load_dotenv
    load_dotenv()
    from admin.seed_demo import seed_demo
    seed_demo()
    print("[reset_demo] Demo reset complete")


if __name__ == "__main__":
    reset()
