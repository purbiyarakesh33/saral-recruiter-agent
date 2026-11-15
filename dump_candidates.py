"""Step 1 of offline tuning. Makes ONE embedding call per benchmark query (20 total).
No chat-model calls, no GitHub calls.

    python dump_candidates.py manual_recruiter_query_rankings.txt

Writes data/evaluation/candidate_dump.json: for every query, every eligible profile with its
cosine similarity and the rubric features that the live ranker computes.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from agent import Config, Database, FeatherlessClient, SearchAgent, VerificationAgent, profile_has_injection
from diagnose_precision import parse

ROOT = Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    queries = parse(Path(sys.argv[1]))
    search = SearchAgent(Database(), FeatherlessClient())
    verifier = VerificationAgent.__new__(VerificationAgent)
    db = sqlite3.connect(Config.db_path)
    try:
        identity = {r[0]: r[1] for r in db.execute("SELECT profile_id,status FROM identity_verifications")}
    except sqlite3.OperationalError:
        identity = {}
    out = []
    for q in queries:
        print(f"{q['id']}: embedding + rubric features", flush=True)
        candidates = []
        for item in search.search(q["query"], 100):
            profile = item["profile"]
            if item["source"] != "github" or profile.get("is_synthetic"):
                continue
            if profile_has_injection(profile, item["display_name"] or ""):
                continue
            if identity.get(item["profile_id"]) not in (None, "github_account_verified"):
                continue
            rubric = verifier._five_factor_rank(q["query"], profile)
            candidates.append({
                "profile_id": item["profile_id"],
                "login": str(profile.get("login") or "").casefold(),
                "similarity": float(item["similarity"]),
                "key": [float(x) for x in rubric["rank_key"]],
                "relevant_repos": len(rubric["relevant_projects"]),
                "authored": int(rubric["authored_relevant_projects"]),
            })
        out.append({"id": q["id"], "query": q["query"], "labels": q["handles"], "candidates": candidates})
    path = ROOT / "data" / "evaluation" / "candidate_dump.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {path} ({len(out)} queries). Next: python tune_offline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
