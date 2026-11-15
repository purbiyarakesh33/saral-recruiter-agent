"""Step 2. Pure offline, no API calls:  python tune_offline.py

Compares the current ranking with cosine-only and with weighted blends of the same rubric features.
Weights are chosen on Q1-Q15 only; Q16-Q20 are reported separately. Leave-one-query-out CV on
Q1-Q15 is the honest estimate, because choosing the best of thousands of weight sets on 15 queries
overfits.
"""
from __future__ import annotations

import itertools
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DUMP = ROOT / "data" / "evaluation" / "candidate_dump.json"
FEATURES = ("grade", "location", "project_relevance", "project_evidence", "skills", "experience", "relevant_repos", "similarity_z")
GRID = {
    "grade": (0, 1, 2, 3), "location": (0, 1, 2), "project_relevance": (0, 1, 2), "project_evidence": (0, 1),
    "skills": (0, 1, 2), "experience": (0, 1), "relevant_repos": (0, 1), "similarity_z": (0, 1, 2, 4),
}
HELD_OUT = {f"Q{n}" for n in range(16, 21)}


def prepare(rows: list[dict]) -> list[dict]:
    prepared = []
    for row in rows:
        sims = [c["similarity"] for c in row["candidates"]]
        mean = statistics.fmean(sims) if sims else 0.0
        sd = statistics.pstdev(sims) or 1.0
        cands = []
        for c in row["candidates"]:
            grade, loc, prel, pev, skills, exp = c["key"]
            cands.append({
                "login": c["login"], "profile_id": c["profile_id"], "sim": c["similarity"],
                "f": (grade, loc, prel, pev, skills, exp, min(c["relevant_repos"], 5) * 0.6, (c["similarity"] - mean) / sd),
            })
        prepared.append({"id": row["id"], "labels": set(row["labels"]), "cands": cands})
    return prepared


def hits(row: dict, weights: tuple[float, ...] | None, mode: str = "blend") -> int:
    cands = sorted(row["cands"], key=lambda c: c["profile_id"])          # deterministic base order
    if mode == "current":                                                  # old behaviour: lexicographic key, profile_id ties
        ranked = sorted(cands, key=lambda c: c["f"][:6], reverse=True)
    elif mode == "current+sim":
        ranked = sorted(cands, key=lambda c: (*c["f"][:6], c["sim"]), reverse=True)
    elif mode == "cosine":
        ranked = sorted(cands, key=lambda c: c["sim"], reverse=True)
    else:
        ranked = sorted(cands, key=lambda c: (sum(w * x for w, x in zip(weights, c["f"])), c["sim"]), reverse=True)
    return sum(c["login"] in row["labels"] for c in ranked[:5])


def pct(h: int, n: int) -> str:
    return f"{h}/{5 * n} = {100 * h / (5 * n):.1f}%" if n else "n/a"


def main() -> int:
    if not DUMP.exists():
        print("Run: python dump_candidates.py manual_recruiter_query_rankings.txt")
        return 2
    rows = prepare(json.loads(DUMP.read_text(encoding="utf-8")))
    dev = [r for r in rows if r["id"] not in HELD_OUT]
    held = [r for r in rows if r["id"] in HELD_OUT]

    print("BASELINES               dev(Q1-15)            held-out(Q16-20, seen)")
    for name in ("current", "current+sim", "cosine"):
        print(f"  {name:<14}  {pct(sum(hits(r, None, name) for r in dev), len(dev)):<22}{pct(sum(hits(r, None, name) for r in held), len(held))}")

    configs = list(itertools.product(*(GRID[f] for f in FEATURES)))
    configs = [w for w in configs if any(w)]
    matrix = {w: [hits(r, w) for r in rows] for w in configs}
    dev_idx = [i for i, r in enumerate(rows) if r["id"] not in HELD_OUT]
    held_idx = [i for i, r in enumerate(rows) if r["id"] in HELD_OUT]

    def best(indices: list[int]) -> tuple[float, ...]:
        return max(configs, key=lambda w: (sum(matrix[w][i] for i in indices), -sum(1 for x in w if x), -sum(w)))

    chosen = best(dev_idx)
    cv = sum(matrix[best([j for j in dev_idx if j != i])][i] for i in dev_idx)
    print(f"\nWeighted blend, {len(configs)} weight sets searched.")
    print(f"  chosen on dev            : {dict(zip(FEATURES, chosen))}")
    print(f"  dev (optimistic)         : {pct(sum(matrix[chosen][i] for i in dev_idx), len(dev_idx))}")
    print(f"  dev leave-one-out (fair) : {pct(cv, len(dev_idx))}")
    print(f"  held-out (seen queries)  : {pct(sum(matrix[chosen][i] for i in held_idx), len(held_idx))}")
    print("  per query hits           : " + ", ".join(f"{rows[i]['id']}={matrix[chosen][i]}" for i in range(len(rows))))
    ceiling = 0
    for r in rows:
        present = sum(c["login"] in r["labels"] for c in r["cands"])
        ceiling += min(5, present)
    print(f"\nLabelled profiles present among eligible candidates: ceiling {ceiling}/{5 * len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
