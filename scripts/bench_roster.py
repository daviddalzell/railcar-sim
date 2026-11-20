#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Benchmark GET /api/cars and GET /api/operations against a seeded roster.

Checks the Phase 1 fixes in docs/perf-800-cars.md hold up at scale by
seeding N cars with waybills against a RUNNING local dev server, then
timing the two endpoints that used to scale with roster size via N+1
queries. tests/test_car_scaling.py asserts the same invariant (query
count independent of roster size) as an automated, CI-enforced test —
this script is for a human to run on demand and see real wall-clock
numbers against a real HTTP server, not a pytest assertion.

Usage:
    AUTH_DISABLED=1 uvicorn main:app --reload      # in one terminal
    python scripts/bench_roster.py                 # in another
    python scripts/bench_roster.py --count 800 --base-url http://127.0.0.1:8000

Seeds data additively and does not clean up afterward — point this at a
throwaway local SQLite database, never at a real tenant.
"""
import argparse
import sys
import time

import requests


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--count", type=int, default=300,
        help="number of cars to seed (default 300; the original plan's target scale is 800)",
    )
    args = parser.parse_args()

    if not any(host in args.base_url for host in ("127.0.0.1", "localhost")):
        print(
            f"Refusing to run against {args.base_url!r} — this script seeds real data "
            "and is meant for a local dev server only.",
            file=sys.stderr,
        )
        sys.exit(1)

    base = args.base_url.rstrip("/")

    try:
        requests.get(f"{base}/health", timeout=5).raise_for_status()
    except requests.RequestException as e:
        print(f"Could not reach {base}/health — is the server running? ({e})", file=sys.stderr)
        sys.exit(1)

    print(f"Seeding {args.count} cars against {base} ...")
    try:
        group = requests.post(f"{base}/api/locations", json={"name": "Bench Yard"})
        group.raise_for_status()
    except requests.RequestException as e:
        print(
            f"Seed request failed ({e}). If this is a 401/403, start the server with "
            "AUTH_DISABLED=1 — this script doesn't authenticate.",
            file=sys.stderr,
        )
        sys.exit(1)
    group_id = group.json()["id"]

    staging = requests.post(f"{base}/api/tracks", json={
        "name": "Bench Staging", "location_type": "staging", "location_id": group_id,
    }).json()["id"]
    mill = requests.post(f"{base}/api/tracks", json={
        "name": "Bench Mill", "location_type": "industry", "location_id": group_id,
    }).json()["id"]
    requests.post(f"{base}/api/industries", json={
        "name": "Bench Mill Industry", "location_id": mill,
        "commodities": "grain", "inbound_car_types": "boxcar", "industry_role": "consumer",
    })

    t0 = time.time()
    for i in range(args.count):
        car_id = requests.post(f"{base}/api/cars", json={
            "car_type": "boxcar", "reporting_marks": "BNCH", "car_number": str(i + 1),
            "current_location_id": staging,
        }).json()["id"]
        wb_id = requests.post(f"{base}/api/waybills", json={
            "name": "bench-wb", "origin_id": staging, "destination_id": mill,
            "commodity": "grain", "required_car_type": "boxcar",
        }).json()["id"]
        requests.put(f"{base}/api/cars/{car_id}/slots", json={
            "slots": [{"slot_index": 0, "waybill_id": wb_id}],
        })
        if (i + 1) % 100 == 0:
            print(f"  seeded {i + 1}/{args.count}")
    print(f"Seeded {args.count} cars in {time.time() - t0:.1f}s\n")

    for endpoint in ("/api/cars", "/api/operations"):
        t0 = time.time()
        resp = requests.get(f"{base}{endpoint}")
        elapsed = time.time() - t0
        resp.raise_for_status()
        n = len(resp.json())
        per_car_ms = elapsed / n * 1000 if n else 0.0
        print(f"GET {endpoint:16s} {elapsed:7.3f}s for {n} cars  ({per_car_ms:.3f} ms/car)")


if __name__ == "__main__":
    main()
