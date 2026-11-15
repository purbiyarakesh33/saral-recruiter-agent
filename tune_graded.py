# """Step B. Pure offline, no API calls:  python tune_graded.py [--model NAME]

# Scores rankers against the LLM 0-3 grades from llm_judge.py (nDCG@5, ~1,200 graded pairs) instead of only the
# 100 gold slots, then reports gold-overlap P@5 beside it. Weights are searched on Q1-Q15 only, with
# leave-one-query-out CV; Q16-Q20 stay a separate (seen) split.

# "judge-led" ranks by the LLM grade itself, so its nDCG is 1.0 by construction and is not shown; compare its
# gold P@5, which is the real test of whether the labels or the ranker are the bottleneck.
# """
# from __future__ import annotations

# import argparse
# import itertools
# import json
# import math
# import statistics

# from agent import RANK_WEIGHTS, Config
# from llm_judge import DUMP, load_grades
# from tune_offline import FEATURES, GRID, HELD_OUT, prepare

# LOC, SKILLS = FEATURES.index("location"), FEATURES.index("skills")


# def dcg(grades: list[int]) -> float:
#     return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


# def ndcg5(ranked: list[dict], pool: list[dict]) -> float | None:
#     ideal = dcg(sorted((c["g"] for c in pool), reverse=True)[:5])
#     return dcg([c["g"] for c in ranked[:5]]) / ideal if ideal else None


# def order(row: dict, mode: str, w: tuple[float, ...] | None = None) -> list[dict]:
#     cands = sorted(row["cands"], key=lambda c: c["profile_id"])  # deterministic base; sort() is stable
#     shipped = lambda c: RANK_WEIGHTS["location"] * c["f"][LOC] + RANK_WEIGHTS["skills"] * c["f"][SKILLS]
#     keys = {
#         "cosine": lambda c: c["sim"],
#         "old": lambda c: c["f"][:6],
#         "shipped": lambda c: (shipped(c), c["sim"]),
#         "judge": lambda c: (c["g"], shipped(c), c["sim"]),
#         "blend": lambda c: (sum(x * y for x, y in zip(w or (), c["f"])), c["sim"]),
#     }
#     return sorted(cands, key=keys[mode], reverse=True)


# def gold_hits(row: dict, ranked: list[dict]) -> int:
#     return sum(c["login"] in row["labels"] for c in ranked[:5])


# def fmt(values: list[float], pct: bool = True) -> str:
#     if not values:
#         return "n/a"
#     mean = statistics.fmean(values)
#     return f"{100 * mean:.1f}%" if pct else f"{mean:.3f}"


# def main() -> int:
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--model", default=None, help="judge model whose cached grades to use")
#     args = parser.parse_args()
#     if args.model:
#         Config.chat_model = args.model
#     if not DUMP.exists():
#         print("Run: python dump_candidates_b.py")
#         return 2
#     raw = json.loads(DUMP.read_text(encoding="utf-8"))
#     grades = load_grades()
#     rows = []
#     for src, prep in zip(raw, prepare(raw)):  # prepare() keeps the order of raw
#         got = [grades.get((src["query"], c["profile_id"])) for c in prep["cands"]]
#         if None in got:
#             print(f"skip {prep['id']}: {got.count(None)}/{len(got)} pairs not judged yet")
#             continue
#         for c, g in zip(prep["cands"], got):
#             c["g"] = g
#         rows.append(prep)
#     if not rows:
#         print("No fully judged queries. Run: python llm_judge.py")
#         return 2
#     dev = [i for i, r in enumerate(rows) if r["id"] not in HELD_OUT]
#     held = [i for i, r in enumerate(rows) if r["id"] in HELD_OUT]
#     print(f"{len(rows)} judged queries ({len(dev)} dev, {len(held)} held-out/seen); judge model {Config.chat_model}\n")

#     def stats(idx: list[int], mode: str) -> tuple[list[float], list[float]]:
#         nd, p5 = [], []
#         for i in idx:
#             ranked = order(rows[i], mode)
#             score = ndcg5(ranked, rows[i]["cands"])
#             if score is not None:
#                 nd.append(score)
#             p5.append(gold_hits(rows[i], ranked) / 5)
#         return nd, p5

#     print(f"{'ranker':<36}{'nDCG@5 dev':<12}{'nDCG@5 held':<13}{'gold P@5 dev':<14}gold P@5 held")
#     for mode, label in (("cosine", "cosine only"), ("old", "old rubric key"),
#                         ("shipped", f"shipped {RANK_WEIGHTS['location']:g}*loc+{RANK_WEIGHTS['skills']:g}*skills"),
#                         ("judge", "judge-led (needs LLM at runtime)")):
#         nd_d, p_d = stats(dev, mode)
#         nd_h, p_h = stats(held, mode)
#         circular = mode == "judge"
#         print(f"{label:<36}{'n/a' if circular else fmt(nd_d):<12}{'n/a' if circular else fmt(nd_h):<13}{fmt(p_d):<14}{fmt(p_h)}")

#     configs = [w for w in itertools.product(*(GRID[f] for f in FEATURES)) if any(w)]
#     nd_matrix = {w: [ndcg5(order(r, "blend", w), r["cands"]) for r in rows] for w in configs}

#     def mean_nd(w: tuple[float, ...], idx: list[int]) -> float:
#         vals = [nd_matrix[w][i] for i in idx if nd_matrix[w][i] is not None]
#         return statistics.fmean(vals) if vals else 0.0

#     def best(idx: list[int]) -> tuple[float, ...]:
#         return max(configs, key=lambda w: (mean_nd(w, idx), -sum(1 for x in w if x), -sum(w)))

#     chosen = best(dev)
#     loo = [nd_matrix[best([j for j in dev if j != i])][i] for i in dev]
#     loo = [v for v in loo if v is not None]
#     hits = lambda idx: sum(gold_hits(rows[i], order(rows[i], "blend", chosen)) for i in idx)
#     print(f"\nBlend searched on LLM grades ({len(configs)} weight sets): {dict(zip(FEATURES, chosen))}")
#     print(f"  nDCG@5 dev (optimistic)     : {mean_nd(chosen, dev):.3f}")
#     print(f"  nDCG@5 dev leave-one-out    : {statistics.fmean(loo):.3f}   <- fair estimate" if loo else "  no LOO data")
#     print(f"  nDCG@5 held-out (seen)      : {mean_nd(chosen, held):.3f}")
#     print(f"  gold P@5 dev / held-out     : {100 * hits(dev) / (5 * len(dev)):.1f}% / {100 * hits(held) / max(1, 5 * len(held)):.1f}%")
#     print("\nReading it: if judge-led gold P@5 is far above shipped, wire the judge into VerificationAgent. "
#           "If it is not, the labels (not the ranker) cap precision; fix the labels first.")
#     return 0


# if __name__ == "__main__":
#     raise SystemExit(main())
"""Step B. Pure offline, no API calls:  python tune_graded.py [--model NAME]

Scores rankers against the LLM 0-3 grades from llm_judge.py (nDCG@5, ~1,200 graded pairs) instead of only the
100 gold slots, then reports gold-overlap P@5 beside it. Weights are searched on Q1-Q15 only, with
leave-one-query-out CV; Q16-Q20 stay a separate (seen) split.

"judge-led" ranks by the LLM grade itself, so its nDCG is 1.0 by construction and is not shown; compare its
gold P@5, which is the real test of whether the labels or the ranker are the bottleneck.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics

from agent import RANK_WEIGHTS, Config
from llm_judge import DUMP, load_grades
from tune_offline import FEATURES, GRID, HELD_OUT, prepare

LOC, SKILLS = FEATURES.index("location"), FEATURES.index("skills")


def dcg(grades: list[int]) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def ndcg5(ranked: list[dict], pool: list[dict]) -> float | None:
    ideal = dcg(sorted((c["g"] for c in pool), reverse=True)[:5])
    return dcg([c["g"] for c in ranked[:5]]) / ideal if ideal else None


def order(row: dict, mode: str, w: tuple[float, ...] | None = None) -> list[dict]:
    cands = sorted(row["cands"], key=lambda c: c["profile_id"])  # deterministic base; sort() is stable
    shipped = lambda c: RANK_WEIGHTS["location"] * c["f"][LOC] + RANK_WEIGHTS["skills"] * c["f"][SKILLS]
    keys = {
        "cosine": lambda c: c["sim"],
        "old": lambda c: c["f"][:6],
        "old_sim": lambda c: (c["f"][:6], c["sim"]),
        "judge_old": lambda c: (c["g"], c["f"][:6], c["sim"]),
        "shipped": lambda c: (shipped(c), c["sim"]),
        "judge": lambda c: (c["g"], shipped(c), c["sim"]),
        "blend": lambda c: (sum(x * y for x, y in zip(w or (), c["f"])), c["sim"]),
    }
    return sorted(cands, key=keys[mode], reverse=True)


def order_topk(row: dict, k: int) -> list[dict]:
    """Live-style: rank by old key + sim, judge only the top k, reorder those k by (grade, old key, sim)."""
    base = order(row, "old_sim")
    head = sorted(base[:k], key=lambda c: (c["g"], c["f"][:6], c["sim"]), reverse=True)
    return head + base[k:]


def gold_hits(row: dict, ranked: list[dict]) -> int:
    return sum(c["login"] in row["labels"] for c in ranked[:5])


def fmt(values: list[float], pct: bool = True) -> str:
    if not values:
        return "n/a"
    mean = statistics.fmean(values)
    return f"{100 * mean:.1f}%" if pct else f"{mean:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="judge model whose cached grades to use")
    args = parser.parse_args()
    if args.model:
        Config.chat_model = args.model
    if not DUMP.exists():
        print("Run: python dump_candidates_b.py")
        return 2
    raw = json.loads(DUMP.read_text(encoding="utf-8"))
    grades = load_grades()
    rows = []
    for src, prep in zip(raw, prepare(raw)):  # prepare() keeps the order of raw
        got = [grades.get((src["query"], c["profile_id"])) for c in prep["cands"]]
        if None in got:
            print(f"skip {prep['id']}: {got.count(None)}/{len(got)} pairs not judged yet")
            continue
        for c, g in zip(prep["cands"], got):
            c["g"] = g
        rows.append(prep)
    if not rows:
        print("No fully judged queries. Run: python llm_judge.py")
        return 2
    dev = [i for i, r in enumerate(rows) if r["id"] not in HELD_OUT]
    held = [i for i, r in enumerate(rows) if r["id"] in HELD_OUT]
    print(f"{len(rows)} judged queries ({len(dev)} dev, {len(held)} held-out/seen); judge model {Config.chat_model}\n")

    def stats(idx: list[int], fn) -> tuple[list[float], list[float]]:
        nd, p5 = [], []
        for i in idx:
            ranked = fn(rows[i])
            score = ndcg5(ranked, rows[i]["cands"])
            if score is not None:
                nd.append(score)
            p5.append(gold_hits(rows[i], ranked) / 5)
        return nd, p5

    print(f"{'ranker':<40}{'nDCG@5 dev':<12}{'nDCG@5 held':<13}{'gold P@5 dev':<14}gold P@5 held")
    table = [("cosine", "cosine only", False), ("old", "old rubric key (profile_id ties)", False),
             ("old_sim", "old rubric key + sim tie-break", False),
             ("shipped", f"shipped {RANK_WEIGHTS['location']:g}*loc+{RANK_WEIGHTS['skills']:g}*skills", False),
             ("judge", "judge all 60, shipped tie-break*", True),
             ("judge_old", "judge all 60, old-key tie-break", True)]
    table += [(f"topk{k}", f"judge top {k} of old key (live-style)", False) for k in (10, 15, 20, 30)]
    for mode, label, circular in table:
        fn = (lambda r, m=mode: order_topk(r, int(m[4:]))) if mode.startswith("topk") else (lambda r, m=mode: order(r, m))
        nd_d, p_d = stats(dev, fn)
        nd_h, p_h = stats(held, fn)
        print(f"{label:<40}{'n/a' if circular else fmt(nd_d):<12}{'n/a' if circular else fmt(nd_h):<13}{fmt(p_d):<14}{fmt(p_h)}")
    print("* tie-break is the blend tuned on dev gold, so its dev column is optimistic; judge-all nDCG is circular (n/a).")

    configs = [w for w in itertools.product(*(GRID[f] for f in FEATURES)) if any(w)]
    nd_matrix = {w: [ndcg5(order(r, "blend", w), r["cands"]) for r in rows] for w in configs}

    def mean_nd(w: tuple[float, ...], idx: list[int]) -> float:
        vals = [nd_matrix[w][i] for i in idx if nd_matrix[w][i] is not None]
        return statistics.fmean(vals) if vals else 0.0

    def best(idx: list[int]) -> tuple[float, ...]:
        return max(configs, key=lambda w: (mean_nd(w, idx), -sum(1 for x in w if x), -sum(w)))

    chosen = best(dev)
    loo = [nd_matrix[best([j for j in dev if j != i])][i] for i in dev]
    loo = [v for v in loo if v is not None]
    hits = lambda idx: sum(gold_hits(rows[i], order(rows[i], "blend", chosen)) for i in idx)
    print(f"\nBlend searched on LLM grades ({len(configs)} weight sets): {dict(zip(FEATURES, chosen))}")
    print(f"  nDCG@5 dev (optimistic)     : {mean_nd(chosen, dev):.3f}")
    print(f"  nDCG@5 dev leave-one-out    : {statistics.fmean(loo):.3f}   <- fair estimate" if loo else "  no LOO data")
    print(f"  nDCG@5 held-out (seen)      : {mean_nd(chosen, held):.3f}")
    print(f"  gold P@5 dev / held-out     : {100 * hits(dev) / (5 * len(dev)):.1f}% / {100 * hits(held) / max(1, 5 * len(held)):.1f}%")
    print("\nReading it: if judge-led gold P@5 is far above shipped, wire the judge into VerificationAgent. "
          "If it is not, the labels (not the ranker) cap precision; fix the labels first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())