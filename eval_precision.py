"""Precision@5 of Saral's ranking vs the manual top-5 for queries 1-15.
Run from project root (beside agent.py, .env, data/):  python eval_precision.py
"""
import re, sys
from pathlib import Path
from agent import RecruiterAgent

FILE = Path("manual_recruiter_query_rankings.txt")
K = 5
text = FILE.read_text(encoding="utf-8")

gold = {}  # n -> (query, [github ids])
for m in re.finditer(r"^(\d+)\. Query: (.+?)\n(.*?)(?=^\d+\. Query:|\Z)", text, re.S | re.M):
    n = int(m.group(1))
    gold[n] = (m.group(2).strip(), re.findall(r"\(github:(\d+)\)", m.group(3)))

agent = RecruiterAgent()
rows = []
for n in range(1, 16):
    query, ids = gold[n]
    assert len(ids) == K, f"Q{n}: expected {K} gold ids, got {len(ids)}"
    res = agent.query(query, K)["results"][:K]
    got = [str((r["profile"] or {}).get("github_id") or re.sub(r"\D", "", r["profile_id"])) for r in res]
    hits = [g for g in got if g in ids]
    rows.append((n, len(hits) / K))
    print(f"Q{n:>2}  P@{K}={len(hits)}/{K}={len(hits)/K:.2f}  missed={[g for g in ids if g not in got]}")

print(f"\nMean P@{K} over 15 queries = {sum(p for _, p in rows) / len(rows):.3f}")
