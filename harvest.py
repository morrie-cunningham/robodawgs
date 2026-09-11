#!/usr/bin/env python3
"""
RoboDawgs award/stats harvester.

Sweeps the RobotEvents (events.vex.com) API v2 for all Grandville RoboDawgs
teams (every letter variant of the base numbers below), keeps only teams whose
organization matches Grandville/RoboDawgs OR whose location is Grandville, MI,
then pulls awards, events, rankings and skills for each team.

Usage:
    python3 harvest.py                 # full harvest -> robodawgs-data.json + robodawgs-data.js
    python3 harvest.py --only=205,2060 # re-harvest just these base numbers, merge into existing data

Requires: ~/Desktop/.re_token containing your RobotEvents API bearer token.
Re-run after each competition weekend to refresh the data.
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://events.vex.com/api/v2"
DESK = Path(__file__).resolve().parent
def _find_token():
    for p in (DESK / ".re_token", Path.home() / ".re_token", Path.home() / "Desktop" / ".re_token"):
        if p.exists():
            return p.read_text().strip()
    sys.exit("No .re_token file found (looked next to harvest.py, in ~, and on ~/Desktop)")


TOKEN = _find_token()

# Base team numbers (letters are swept A-Z automatically, plus the bare number)
BASE_NUMBERS = [
    # High School (V5RC)
    "244", "248", "288",
    # Middle School (V5RC)
    "216", "13000", "13002", "41000",
    # Elementary (VIQRC)
    "2060", "201", "202", "203", "204", "205", "206", "207", "208",
    # VEX AI
    "1248",
]

ORG_PATTERN = re.compile(r"grandville|robodawg", re.I)


def is_grandville(t):
    """Org name mentions Grandville/RoboDawgs, or the team is located in Grandville, MI."""
    if ORG_PATTERN.search(t.get("organization") or ""):
        return True
    loc = t.get("location") or {}
    return (loc.get("city") or "").strip().lower() == "grandville" and \
           (loc.get("region") or "").strip().lower() == "michigan"

REQ_DELAY = 0.30  # seconds between requests (be nice to the API)


def api_get(path, params=None, retries=5):
    """GET one page from the API with retry/backoff."""
    qs = urllib.parse.urlencode(params or [], doseq=True)
    url = f"{API}{path}" + (f"?{qs}" if qs else "")
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            "User-Agent": "robodawgs-harvest/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(REQ_DELAY)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = 2 ** (attempt + 1)
                print(f"  HTTP {e.code} on {path}, retrying in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            wait = 2 ** (attempt + 1)
            print(f"  network error on {path}, retrying in {wait}s...", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"gave up on {url}")


def api_get_all(path, params=None):
    """Follow pagination, return concatenated data[]."""
    params = list(params or [])
    params.append(("per_page", 250))
    out, page = [], 1
    while True:
        data = api_get(path, params + [("page", page)])
        out.extend(data.get("data", []))
        meta = data.get("meta", {})
        if not meta.get("next_page_url"):
            break
        page += 1
    return out


def find_teams(bases=None):
    """Search every number+letter variant; keep Grandville teams only."""
    variants = []
    for base in (bases or BASE_NUMBERS):
        variants.append(base)
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            variants.append(base + ch)

    teams = {}
    BATCH = 20
    for i in range(0, len(variants), BATCH):
        chunk = variants[i:i + BATCH]
        params = [("number[]", v) for v in chunk]
        print(f"Searching teams {i + 1}-{i + len(chunk)} of {len(variants)}...", flush=True)
        for t in api_get_all("/teams", params):
            org = t.get("organization") or ""
            if is_grandville(t) and t["id"] not in teams:
                teams[t["id"]] = {
                    "id": t["id"],
                    "number": t["number"],
                    "name": t.get("team_name") or "",
                    "robot": t.get("robot_name") or "",
                    "organization": org,
                    "grade": t.get("grade") or "",
                    "program": (t.get("program") or {}).get("code") or "",
                    "programId": (t.get("program") or {}).get("id"),
                    "registered": t.get("registered", False),
                    "city": ((t.get("location") or {}).get("city")) or "",
                }
                print(f"  + {t['number']} ({org}) [{teams[t['id']]['program']}]", flush=True)
    return teams


def slim_event(e):
    return {
        "id": e["id"],
        "sku": e.get("sku", ""),
        "name": e.get("name", ""),
        "start": (e.get("start") or "")[:10],
        "seasonId": (e.get("season") or {}).get("id"),
        "season": (e.get("season") or {}).get("name") or "",
        "level": e.get("level") or "",
        "eventType": e.get("event_type") or "",
        "city": ((e.get("location") or {}).get("city")) or "",
        "region": ((e.get("location") or {}).get("region")) or "",
        "country": ((e.get("location") or {}).get("country")) or "",
    }


def main():
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    only = None
    for arg in sys.argv[1:]:
        if arg.startswith("--only"):
            only = arg.split("=", 1)[1].split(",") if "=" in arg else None
    if only:
        print(f"Supplemental harvest for base numbers: {only}\n", flush=True)
    teams = find_teams(only)
    print(f"\nFound {len(teams)} Grandville teams. Fetching per-team data...\n", flush=True)

    events = {}          # eventId -> event info (deduped)
    awards = []
    rankings = []
    skills = []

    for n, (tid, team) in enumerate(sorted(teams.items(), key=lambda kv: kv[1]["number"]), 1):
        print(f"[{n}/{len(teams)}] {team['number']} ({team['program']})", flush=True)

        evts = api_get_all(f"/teams/{tid}/events")
        for e in evts:
            events.setdefault(e["id"], slim_event(e))
        team["eventIds"] = [e["id"] for e in evts]

        for a in api_get_all(f"/teams/{tid}/awards"):
            awards.append({
                "teamId": tid,
                "teamNumber": team["number"],
                "title": a.get("title", ""),
                "eventId": (a.get("event") or {}).get("id"),
                "eventName": (a.get("event") or {}).get("name") or "",
                "qualifications": a.get("qualifications") or [],
            })

        for r in api_get_all(f"/teams/{tid}/rankings"):
            rankings.append({
                "teamId": tid,
                "teamNumber": team["number"],
                "eventId": (r.get("event") or {}).get("id"),
                "rank": r.get("rank"),
                "wins": r.get("wins"), "losses": r.get("losses"), "ties": r.get("ties"),
                "wp": r.get("wp"), "ap": r.get("ap"), "sp": r.get("sp"),
                "high_score": r.get("high_score"),
            })

        for s in api_get_all(f"/teams/{tid}/skills"):
            skills.append({
                "teamId": tid,
                "teamNumber": team["number"],
                "eventId": (s.get("event") or {}).get("id"),
                "seasonId": (s.get("season") or {}).get("id"),
                "type": s.get("type") or "",
                "score": s.get("score"),
                "rank": s.get("rank"),
            })

        aw = sum(1 for a in awards if a["teamId"] == tid)
        print(f"    {len(evts)} events, {aw} awards", flush=True)

    payload = {
        "generatedAt": started,
        "teams": list(teams.values()),
        "events": list(events.values()),
        "awards": awards,
        "rankings": rankings,
        "skills": skills,
    }

    if only:
        # Merge into the existing dataset instead of replacing it
        existing_path = DESK / "robodawgs-data.json"
        if existing_path.exists():
            old = json.loads(existing_path.read_text())
            new_team_ids = {t["id"] for t in payload["teams"]}
            merged_teams = [t for t in old["teams"] if t["id"] not in new_team_ids] + payload["teams"]
            ev_map = {e["id"]: e for e in old["events"]}
            ev_map.update({e["id"]: e for e in payload["events"]})
            def keep(rows):  # drop old rows for re-harvested teams
                return [r for r in rows if r["teamId"] not in new_team_ids]
            payload = {
                "generatedAt": started,
                "teams": merged_teams,
                "events": list(ev_map.values()),
                "awards": keep(old["awards"]) + payload["awards"],
                "rankings": keep(old["rankings"]) + payload["rankings"],
                "skills": keep(old["skills"]) + payload["skills"],
            }
            print(f"Merged with existing data: now {len(payload['teams'])} teams total")

    (DESK / "robodawgs-data.json").write_text(json.dumps(payload, indent=1))
    (DESK / "robodawgs-data.js").write_text(
        "// Auto-generated by harvest.py — do not edit by hand\n"
        "window.ROBODAWGS_DATA = " + json.dumps(payload) + ";\n"
    )
    print(f"\nDone. {len(teams)} teams, {len(events)} events, {len(awards)} awards, "
          f"{len(rankings)} rankings, {len(skills)} skills runs.")
    print("Wrote robodawgs-data.json and robodawgs-data.js")


if __name__ == "__main__":
    main()
