"""Offline precision diagnosis. No LLM, no GitHub, no embedding calls.

Usage (from the project root, beside agent.py and data/):
    python diagnose_precision.py manual_recruiter_query_rankings.txt

For every benchmark query it replays the deterministic part of the ranker
(injection screen, cached GitHub identity status, five-factor rubric key) and
reports why labelled profiles are missed:
  - EXCLUDED : labelled profile never reaches the shortlist (injection regex or
               non-verified GitHub identity in the cache)
  - TIE      : labelled profile ties on the rubric key at the cut-off, so the old
               code ordered it by profile_id (arbitrary)
  - LOW      : rubric ranks it clearly below the cut-off (rubric disagrees with label)
Cosine similarity needs a live embedding call, so it is not replayed here;
"ceiling" is what a perfect tie-break could reach, "old" replays profile_id order.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from agent import Config, VerificationAgent, profile_has_injection

QUERY = re.compile(r"(?m)^\s*(\d+)\.\s+Query:\s*(.+?)\s*$")
HANDLE = re.compile(r"@([A-Za-z0-9-]+)\s*\(github:")


def parse(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    heads = list(QUERY.finditer(text))
    rows = []
    for i, head in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        handles = [h.casefold() for h in HANDLE.findall(text[head.end():stop])]
        rows.append({"id": f"Q{head.group(1)}", "query": head.group(2), "handles": handles})
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    queries = parse(Path(sys.argv[1]))
    db = sqlite3.connect(Config.db_path)
    db.row_factory = sqlite3.Row
    profiles = []
    for row in db.execute("SELECT profile_id,source,display_name,profile_json FROM candidate_profiles"):
        profile = json.loads(row["profile_json"])
        if row["source"] != "github" or profile.get("is_synthetic"):
            continue
        profiles.append({"profile_id": row["profile_id"], "display_name": row["display_name"], "profile": profile})
    try:
        identity = {r["profile_id"]: r["status"] for r in db.execute("SELECT profile_id,status FROM identity_verifications")}
    except sqlite3.OperationalError:
        identity = {}
    verifier = VerificationAgent.__new__(VerificationAgent)

    reason: dict[str, str] = {}
    for p in profiles:
        if profile_has_injection(p["profile"], p["display_name"] or ""):
            reason[p["profile_id"]] = "injection-regex"
        elif identity.get(p["profile_id"]) not in (None, "github_account_verified"):
            reason[p["profile_id"]] = f"identity:{identity[p['profile_id']]}"
    print(f"{len(profiles)} real profiles; excluded before ranking: {len(reason)} {dict(Counter(reason.values()))}")
    for pid, why in reason.items():
        login = next(p["profile"].get("login") for p in profiles if p["profile_id"] == pid)
        print(f"   - @{login}: {why}")

    totals = Counter()
    for q in queries:
        scored = []
        for p in profiles:
            if p["profile_id"] in reason:
                continue
            r = verifier._five_factor_rank(q["query"], p["profile"])
            scored.append((p, r["rank_key"], r["relevance_grade"]))
        label = set(q["handles"])
        login = lambda p: str(p["profile"].get("login") or "").casefold()
        old = sorted(sorted(scored, key=lambda x: x[0]["profile_id"]), key=lambda x: x[1], reverse=True)
        old_hits = sum(login(x[0]) in label for x in old[:5])
        cut_key = old[4][1] if len(old) >= 5 else None
        above = [x for x in old if x[1] > cut_key] if cut_key else []
        tied = [x for x in old if x[1] == cut_key] if cut_key else []
        slots = 5 - len(above)
        tied_label = sum(login(x[0]) in label for x in tied)
        ceiling = sum(login(x[0]) in label for x in above) + min(slots, tied_label)
        random_expect = sum(login(x[0]) in label for x in above) + slots * tied_label / max(1, len(tied))
        totals["old"] += old_hits
        totals["ceiling"] += ceiling
        totals["random"] += random_expect
        print(f"\n{q['id']}  old={old_hits}/5  tie-break ceiling={ceiling}/5  tie size={len(tied)}  | {q['query'][:80]}")
        position = {x[0]["profile_id"]: i for i, x in enumerate(old, 1)}
        for handle in q["handles"]:
            hit = next((x for x in old if login(x[0]) == handle), None)
            if hit is None:
                why = next((reason[p["profile_id"]] for p in profiles
                            if login(p) == handle and p["profile_id"] in reason), "not in DB")
                print(f"   @{handle}: EXCLUDED ({why})")
            else:
                pos = position[hit[0]["profile_id"]]
                kind = "in top5" if pos <= 5 else ("TIE" if hit[1] == cut_key else "LOW")
                print(f"   @{handle}: rank {pos} grade={hit[2]} {kind}")
    n = 5 * len(queries)
    print(f"\nOFFLINE (no similarity): old order {totals['old']}/{n} = {100*totals['old']/n:.1f}% | "
          f"random tie-break {totals['random']:.1f}/{n} = {100*totals['random']/n:.1f}% | "
          f"perfect tie-break ceiling {totals['ceiling']}/{n} = {100*totals['ceiling']/n:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
