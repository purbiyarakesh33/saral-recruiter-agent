"""Dump full eligible candidate pools + rubric features for Q1-Q20, labelled from the SAME benchmark
file run_benchmark_precision.py scores against, in the format tune_offline.py reads.

Run:  python dump_candidates_b.py [--benchmark "C:\\Users\\Admin\\Downloads\\saral_recruiter_benchmark.txt"]
Then: python tune_offline.py

Writes data/evaluation/candidate_dump.json. An existing dump is first copied to
candidate_dump.previous.json, so the old (manual_recruiter_query_rankings.txt) labels are not lost.
Live calls: one embedding + the normal verification model calls per query, like a benchmark run.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import run_benchmark_precision as rbp  # noqa: E402  (parse_benchmark, candidate_login: the runner's own gold)
from agent import RecruiterAgent  # noqa: E402

OUT = ROOT / "data" / "evaluation" / "candidate_dump.json"


def candidate_row(result: dict) -> dict:
    comp = result.get("rubric_components") or {}
    return {
        "login": rbp.candidate_login(result).casefold(),
        "profile_id": result["profile_id"],
        "similarity": float(result["similarity"]),
        # same order as _rubric_sort_key in agent.py: grade, location, project_relevance, project_evidence, skills, experience
        "key": [
            int(result.get("relevance_grade") or 0),
            float(comp.get("location", 0.0)),
            float(comp.get("project_relevance", 0.0)),
            float(comp.get("project_evidence", 0.0)),
            float(comp.get("skills", 0.0)),
            float(comp.get("experience_activity", 0.0)),
        ],
        "relevant_repos": len(result.get("relevant_projects") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump candidate pools labelled from the runner's benchmark.")
    parser.add_argument("--benchmark", type=Path, default=rbp.DEFAULT_BENCHMARK)
    args = parser.parse_args()
    try:
        queries = rbp.parse_benchmark(args.benchmark.expanduser().resolve())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    agent = RecruiterAgent()
    rows = []
    for q in queries:
        pool = agent.search_agent.search(q["query"], 100)
        verified = agent.verification_agent.verify_and_rank(q["query"], pool)
        eligible = [r for r in verified["results"] if r.get("eligible_for_shortlist")]
        labels = sorted(h.casefold() for h in q["handles"])
        cands = [candidate_row(r) for r in eligible]
        present = sum(c["login"] in set(labels) for c in cands)
        rows.append({"id": q["id"], "query": q["query"], "labels": labels, "candidates": cands})
        print(f"{q['id']}: {len(cands)} eligible candidates, {present}/{len(labels)} gold handles present", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        shutil.copyfile(OUT, OUT.with_name("candidate_dump.previous.json"))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {len(rows)} queries to {OUT}")
    print(f"Gold source: {args.benchmark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
