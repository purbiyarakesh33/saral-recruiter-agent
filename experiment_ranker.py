from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVAL = ROOT / "data" / "evaluation"
WEIGHT_OPTIONS = (
    (0, 2.5, 5, 7.5, 10),  # semantic similarity
    (0, 0.5, 1, 1.5, 2, 3, 4),  # deterministic evidence score
    (0, 1, 2, 3, 4),  # supported claims
    (0, 1, 2, 3, 4),  # contradicted claims penalty
    (0, 0.25, 0.5, 1),  # unverified claims penalty
    (0, 0.25, 0.5, 1),  # matched evidence count
    (0, 0.25, 0.5, 1),  # missing evidence penalty
)


def latest_full_report() -> tuple[Path, dict]:
    paths = sorted(EVAL.glob("benchmark_overlap_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        state = json.loads(path.read_text(encoding="utf-8"))
        rows = [row for row in state.get("queries", []) if row.get("status") == "completed"]
        if rows and all(row.get("ranked_candidates") for row in rows):
            return path, state
    raise SystemExit("No fresh report with complete ranked candidates. Run run_benchmark_precision.py first.")


def features(candidate: dict) -> tuple[float, ...]:
    return (
        float(candidate.get("similarity") or 0),
        float(candidate.get("evidence_score") or 0),
        float(candidate.get("supported_claims") or 0),
        float(candidate.get("contradicted_claims") or 0),
        float(candidate.get("unverified_claims") or 0),
        float(len(candidate.get("matched_evidence") or [])),
        float(len(candidate.get("missing_evidence") or [])),
    )


def score(candidate: dict, weights: tuple[float, ...]) -> float:
    values = features(candidate)
    return sum(weight * value * (1 if index in (0, 1, 2, 5) else -1)
               for index, (weight, value) in enumerate(zip(weights, values)))


def evaluate(rows: list[dict], weights: tuple[float, ...] | None) -> tuple[int, dict[str, int]]:
    total = 0
    by_query = {}
    for row in rows:
        eligible = [item for item in row["ranked_candidates"] if item.get("eligible_for_shortlist")]
        if weights is None:
            ranked = sorted(eligible, key=lambda item: (item.get("rank_score", 0), item.get("similarity", 0)), reverse=True)
        else:
            ranked = sorted(eligible, key=lambda item: (score(item, weights), item.get("similarity", 0)), reverse=True)
        top_ids = {item["profile_id"] for item in ranked[:5]}
        hits = len(top_ids & set(row["benchmark_ids"]))
        by_query[row["query_id"]] = hits
        total += hits
    return total, by_query


def main() -> None:
    source_path, state = latest_full_report()
    rows = [row for row in state["queries"] if row.get("status") == "completed"]
    if len(rows) < 15:
        raise SystemExit(f"Need all 15 fresh queries before tuning; found {len(rows)}.")
    baseline, baseline_by_query = evaluate(rows, None)

    rng = random.Random(20261111)
    configs: dict[tuple[float, ...], str] = {
        (5, 1, 2, 2, 0.25, 0, 0): "current formula"
    }
    while len(configs) < 100:
        weights = tuple(float(rng.choice(values)) for values in WEIGHT_OPTIONS)
        configs.setdefault(weights, f"variant {len(configs):03d}")

    scored = []
    for weights, name in configs.items():
        hits, per_query = evaluate(rows, weights)
        scored.append({
            "name": name,
            "weights": list(weights),
            "hits": hits,
            "P_at_5": hits / (5 * len(rows)),
            "percent": round(100 * hits / (5 * len(rows)), 2),
            "per_query_hits": per_query,
        })
    scored.sort(key=lambda item: (item["hits"], -sum(item["weights"])), reverse=True)

    coverage = {}
    for row in rows:
        eligible_ids = {item["profile_id"] for item in row["ranked_candidates"] if item.get("eligible_for_shortlist")}
        coverage[row["query_id"]] = len(eligible_ids & set(row["benchmark_ids"]))
    ceiling_hits = sum(min(5, count) for count in coverage.values())

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = EVAL / f"ranker_experiments_{stamp}.json"
    txt_path = EVAL / f"ranker_experiments_{stamp}.txt"
    output = {
        "source_fresh_run": str(source_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_queries": len(rows),
        "metric": "exact overlap with manually ranked top-five GitHub IDs; grades ignored",
        "candidate_pool_ceiling_hits": ceiling_hits,
        "candidate_pool_slots": 5 * len(rows),
        "baseline_hits": baseline,
        "baseline_percent": round(100 * baseline / (5 * len(rows)), 2),
        "tested_weight_configurations": len(scored),
        "best_variants": scored[:20],
        "candidate_pool_coverage": coverage,
    }
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"Offline ranking-weight sweep over {len(rows)} fresh queries",
        f"Source: {source_path}",
        "Method: same fresh candidate results; test 100 general score-weight combinations, no candidate-ID rules.",
        f"Current formula: {baseline}/{5 * len(rows)} = {100 * baseline / (5 * len(rows)):.2f}%.",
        f"Maximum possible from eligible candidate pools: {ceiling_hits}/{5 * len(rows)} = {100 * ceiling_hits / (5 * len(rows)):.2f}%.",
        "",
        "Best variants (similarity, evidence, supported, contradicted penalty, unverified penalty, matched, missing penalty):",
    ]
    for item in scored[:20]:
        lines.append(
            f"{item['name']}: {item['hits']}/{5 * len(rows)} = {item['percent']:.2f}% "
            f"weights={item['weights']}"
        )
        lines.append("  per-query: " + ", ".join(f"{qid}={hit}/5" for qid, hit in item["per_query_hits"].items()))
    lines += ["", "Eligible benchmark candidates present in each captured pool:"]
    lines += [f"{qid}: {hits}/5" for qid, hits in coverage.items()]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Current: {baseline}/{5 * len(rows)} = {100 * baseline / (5 * len(rows)):.2f}%")
    print(f"Pool ceiling: {ceiling_hits}/{5 * len(rows)} = {100 * ceiling_hits / (5 * len(rows)):.2f}%")
    print(f"{len(scored)} variants tested. Best: {scored[0]['hits']}/{5 * len(rows)} = {scored[0]['percent']:.2f}%")
    print(f"Weights: {scored[0]['weights']}")
    print(f"Report: {txt_path}")


if __name__ == "__main__":
    main()
