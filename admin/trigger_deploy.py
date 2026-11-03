# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Fire the nightly deploy workflow on demand — called from /admin/trigger-deploy.

GitHub's own `schedule:` cron trigger has no delivery-time guarantee and has
been observed firing hours late. An external HTTP cron (holding only the
app's existing SYNC_SECRET, not this module's PAT) hits /admin/trigger-deploy
at the desired time instead; this module makes the actual GitHub API call
server-side so the PAT never leaves Fly.

Required env vars:
  GITHUB_DEPLOY_PAT  Fine-grained GitHub PAT scoped to this repo,
                      Actions: write + Contents: read

Usage:
  python -m admin.trigger_deploy
"""

import logging
import os

import requests

GITHUB_API = "https://api.github.com/repos/daviddalzell/railcar-sim/actions/workflows/deploy.yml/dispatches"

logger = logging.getLogger("waypoint.trigger_deploy")


def trigger(ref: str = "main") -> dict:
    """Dispatch the Test & Deploy workflow. Raises on failure."""
    token = os.environ.get("GITHUB_DEPLOY_PAT")
    if not token:
        raise RuntimeError("GITHUB_DEPLOY_PAT is not set")

    resp = requests.post(
        GITHUB_API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"ref": ref},
        timeout=10,
    )
    if resp.status_code != 204:
        logger.error(f"GitHub dispatch failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()

    logger.info(f"Dispatched deploy.yml workflow_dispatch on {ref}")
    return {"ok": True, "ref": ref}


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(trigger(), indent=2))
