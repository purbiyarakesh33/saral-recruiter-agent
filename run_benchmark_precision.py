"""Run every query in the manual benchmark and report exact handle-overlap P@5.

This runner uses the live RecruiterAgent; it never loads saved retrieval results.
Benchmark handles are used only for measurement, never as ranking features.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import RecruiterAgent

ROOT = Path(__file__).resolve().parent
DEFAULT_BENCHMARK = Path(r"C:\Users\Admin\Downloads\saral_recruiter_benchmark.txt")
QUERY_HEADER = re.compile(r"(?m)^Q(?P<id>\d+)\s*[—–-]\s*(?P<query>[^\r\n]+)$")
GITHUB_HANDLE = re.compile(r"(?mi)^\s*GitHub:\s*https?://github\.com/([A-Za-z0-9-]+)")


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_benchmark(path: Path) -> list[dict[str, Any]]:
    text = read_text(path)
    headers = list(QUERY_HEADER.finditer(text))
    if not headers:
        raise ValueError(f"No Q<number> query headings found in benchmark: {path}")

    queries: list[dict[str, Any]] = []
    for index, header in enumerate(headers):
        stop = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        section = text[header.end():stop]
        query = re.sub(r"^\.\s*", "", header.group("query").strip())
        query = re.sub(r"\s+", " ", query)
        handles = {match.group(1).casefold() for match in GITHUB_HANDLE.finditer(section)}
        if not handles:
            raise ValueError(f"No GitHub benchmark handles found for Q{header.group('id')}.")
        queries.append({"id": f"Q{header.group('id')}", "query": query, "handles": handles})
    return queries


def candidate_login(candidate: dict[str, Any]) -> str:
    profile = candidate.get("profile") or {}
    login = str(profile.get("login") or "").strip()
    if login:
        return login
    url = str(profile.get("github_url") or candidate.get("github_url") or "")
    match = re.search(r"github\.com/([^/?#]+)", url, re.I)
    return match.group(1) if match else ""


HELD_OUT = {f"Q{n}" for n in range(16, 21)}


def split_totals(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """(hits, denominator) for development queries and for the held-out five, kept separate."""
    out = {}
    for name, keep in (("development", lambda r: r["id"] not in HELD_OUT), ("held_out", lambda r: r["id"] in HELD_OUT)):
        subset = [r for r in rows if keep(r)]
        out[name] = (sum(r["hits"] for r in subset), 5 * len(subset))
    return out


def format_split(rows: list[dict[str, Any]]) -> list[str]:
    lines = []
    for name, (hits, denom) in split_totals(rows).items():
        pct = f"{100 * hits / denom:.2f}%" if denom else "n/a"
        lines.append(f"{name} P@5: {hits}/{denom} = {pct}")
    return lines


def save_report(
    rows: list[dict[str, Any]], benchmark_path: Path, interrupted: str | None, expected_count: int
) -> tuple[Path, Path, int, int]:
    hits = sum(row["hits"] for row in rows)
    denominator = 5 * len(rows)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "data" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"fresh_precision_{stamp}.json"
    text_path = output_dir / f"fresh_precision_{stamp}.txt"
    payload = {
        "run_type": "fresh live agent retrieval; exact GitHub-handle overlap with supplied benchmark lists",
        "benchmark_path": str(benchmark_path),
        "ranking_method": "shared five-factor 0-3 rubric in VerificationAgent; benchmark handles are measurement-only",
        "metric": "P@5 = returned top-five handles present in that query's listed benchmark handles, divided by 5",
        "benchmark_scores_used": False,
        "queries_completed": len(rows),
        "queries_expected": expected_count,
        "completed": interrupted is None,
        "interruption_or_error": interrupted,
        "benchmark_listed_handles": sum(row["benchmark_handle_count"] for row in rows),
        "hits": hits,
        "denominator": denominator,
        "p_at_5": round(hits / denominator, 6) if denominator else None,
        "split": {k: {"hits": h, "denominator": d} for k, (h, d) in split_totals(rows).items()},
        "queries": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "Saral recruiter benchmark: fresh P@5 exact handle overlap",
        f"Benchmark: {benchmark_path}",
        "Metric: returned top-five GitHub handles found in the matching query's manual benchmark list, divided by 5.",
        "Note: this is exact-list overlap against the supplied heuristic benchmark, not a complete 60-profile relevance judgment.",
        "",
    ]
    for row in rows:
        lines.append(f"{row['id']} | P@5 {row['hits']}/5 | {row['query']}")
        for item in row["results"]:
            mark = "MATCH" if item["benchmark_match"] else "MISS"
            lines.append(f"  {item['rank']}. @{item['login'] or item['display_name']} [{mark}] grade={item['relevance_grade']}")
    pct = 100 * hits / denominator if denominator else 0.0
    lines.extend(["", f"Completed-query P@5: {hits}/{denominator} = {pct:.2f}%.", *format_split(rows)])
    if interrupted:
        lines.append(f"Run stopped before completion: {interrupted}")
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, text_path, hits, denominator


def main() -> int:
    parser = argparse.ArgumentParser(description="Freshly run benchmark queries and calculate exact-handle P@5.")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK,
                        help="Benchmark text file containing Q headings and GitHub profile URLs.")
    args = parser.parse_args()
    benchmark_path = args.benchmark.expanduser().resolve()
    try:
        queries = parse_benchmark(benchmark_path)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Parsed {len(queries)} benchmark queries; starting fresh top-five retrieval.", flush=True)
    agent = RecruiterAgent()
    rows: list[dict[str, Any]] = []
    interrupted: str | None = None
    try:
        for query_row in queries:
            query = query_row["query"]
            print(f"\nRunning {query_row['id']}: {query}", flush=True)
            result = agent.query(query, 5)
            shortlist = list(result.get("shortlist") or [])[:5]
            query_results = []
            query_hits = 0
            for rank, candidate in enumerate(shortlist, 1):
                login = candidate_login(candidate)
                matched = bool(login and login.casefold() in query_row["handles"])
                query_hits += int(matched)
                query_results.append({
                    "rank": rank,
                    "profile_id": candidate.get("profile_id"),
                    "display_name": candidate.get("display_name"),
                    "login": login,
                    "benchmark_match": matched,
                    "relevance_grade": candidate.get("relevance_grade"),
                    "rank_score": candidate.get("rank_score"),
                })
            row = {
                "id": query_row["id"],
                "query": query,
                "hits": query_hits,
                "denominator": 5,
                "benchmark_handle_count": len(query_row["handles"]),
                "results": query_results,
            }
            rows.append(row)
            running_denominator = 5 * len(rows)
            running_hits = sum(item["hits"] for item in rows)
            print(f"{query_row['id']} P@5: {query_hits}/5; completed total {running_hits}/{running_denominator} ({100 * running_hits / running_denominator:.2f}%).", flush=True)
            for item in query_results:
                mark = "MATCH" if item["benchmark_match"] else "MISS"
                print(f"  {item['rank']}. @{item['login'] or item['display_name']} [{mark}] grade={item['relevance_grade']}", flush=True)
    except KeyboardInterrupt:
        interrupted = "interrupted by user"
    except Exception as exc:
        interrupted = f"{type(exc).__name__}: {exc}"
        print(f"Run stopped: {interrupted}", file=sys.stderr, flush=True)

    json_path, text_path, hits, denominator = save_report(rows, benchmark_path, interrupted, len(queries))
    pct = 100 * hits / denominator if denominator else 0.0
    print(f"\nCompleted {len(rows)}/{len(queries)} queries. Exact-list overlap P@5: {hits}/{denominator} = {pct:.2f}%.")
    for line in format_split(rows):
        print(line)
    print(f"JSON report: {json_path}")
    print(f"Text report: {text_path}")
    return 0 if interrupted is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
