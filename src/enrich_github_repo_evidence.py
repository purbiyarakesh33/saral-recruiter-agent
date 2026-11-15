"""Backfill public fork and commit-author evidence for indexed GitHub repos.

Run from the Saral project root:
    python src/enrich_github_repo_evidence.py

Only existing real-profile repository rows are updated. API failures remain
unverified; they are never turned into negative authorship claims.
"""
from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Config  # noqa: E402

API = "https://api.github.com"
MAX_AUTHORSHIP_CHECKS_PER_PROFILE = 3
MAX_WORKERS = 8
TUTORIAL_TERMS = ("tutorial", "starter-code", "course-clone")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Saral-Recruiter-Agent"}
    if Config.github_token:
        headers["Authorization"] = f"Bearer {Config.github_token}"
    return headers


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _canonical_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value or "")
    if parsed.netloc.casefold() not in {"github.com", "www.github.com"}:
        return ""
    return parsed.path.strip("/").removesuffix(".git").casefold()


def _repo_is_checkable(repo: dict[str, Any]) -> bool:
    name = str(repo.get("name") or "").casefold()
    try:
        size = int(repo.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return repo.get("fork") is False and size > 0 and not any(term in name for term in TUTORIAL_TERMS)


def _account_repositories(profile: dict[str, Any]) -> tuple[str, list[dict[str, Any]] | None]:
    login = str(profile.get("login") or "").strip()
    if not login:
        return "missing_login", None
    url = f"{API}/users/{urllib.parse.quote(login, safe='')}/repos?per_page=100&sort=updated"
    try:
        result = _get_json(url)
        return ("ok", result) if isinstance(result, list) else ("invalid_response", None)
    except urllib.error.HTTPError as exc:
        return (f"http_{exc.code}", None)
    except Exception as exc:
        return (type(exc).__name__, None)


def _author_commit(repo: dict[str, Any], login: str, expected_github_id: int | None) -> tuple[str, int | None]:
    full_name = str(repo.get("full_name") or "")
    if not full_name:
        return "missing_repository_name", None
    query = urllib.parse.urlencode({"author": login, "per_page": 1})
    url = f"{API}/repos/{urllib.parse.quote(full_name, safe='/')}/commits?{query}"
    try:
        result = _get_json(url)
        if not isinstance(result, list) or not result:
            return "no_matching_commit", None
        author = result[0].get("author") or {}
        author_id = author.get("id")
        if expected_github_id is not None and author_id is not None and int(author_id) == int(expected_github_id):
            return "confirmed_by_commit_author_id", int(author_id)
        return "commit_author_not_linked_to_profile", int(author_id) if author_id is not None else None
    except urllib.error.HTTPError as exc:
        return f"http_{exc.code}", None
    except Exception as exc:
        return type(exc).__name__, None


def main() -> int:
    db_path = Config.db_path
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}.before_repo_evidence_{stamp}{db_path.suffix}")

    connection = sqlite3.connect(db_path, timeout=30)
    try:
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()

        rows = connection.execute(
            "SELECT profile_id,display_name,profile_json FROM candidate_profiles WHERE source='github' ORDER BY profile_id"
        ).fetchall()
        profiles = [
            {"profile_id": row[0], "display_name": row[1], "profile": json.loads(row[2])}
            for row in rows
        ]
        print(f"Checking repository metadata for {len(profiles)} real profiles.", flush=True)

        account_results: dict[str, tuple[str, list[dict[str, Any]] | None]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_account_repositories, item["profile"]): item["profile_id"] for item in profiles}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                account_results[futures[future]] = future.result()
                if index % 10 == 0 or index == len(futures):
                    print(f"Repository-list requests completed: {index}/{len(futures)}.", flush=True)

        author_jobs: list[tuple[str, dict[str, Any], dict[str, Any], str, int | None]] = []
        now = datetime.now(timezone.utc).isoformat()
        repo_updates = 0
        accounts_ok = sum(status == "ok" for status, _ in account_results.values())
        for item in profiles:
            profile_id, profile = item["profile_id"], item["profile"]
            status, account_repos = account_results.get(profile_id, ("unavailable", None))
            profile["repository_evidence_enrichment"] = {
                "checked_at": now,
                "source": "GitHub REST API",
                "account_repositories_status": status,
                "authorship_check_scope": f"At most {MAX_AUTHORSHIP_CHECKS_PER_PROFILE} non-fork, non-empty repos per profile",
            }
            if not account_repos:
                continue
            by_url = {_canonical_url(str(repo.get("html_url") or "")): repo for repo in account_repos}
            saved_repos = profile.get("repositories") or []
            for repo in saved_repos:
                if not isinstance(repo, dict):
                    continue
                metadata = by_url.get(_canonical_url(str(repo.get("url") or "")))
                if not metadata:
                    continue
                repo["fork"] = bool(metadata.get("fork"))
                repo["size"] = int(metadata.get("size") or 0)
                repo["pushed_at"] = metadata.get("pushed_at")
                repo["owner_login"] = (metadata.get("owner") or {}).get("login")
                repo["repo_metadata_checked_at"] = now
                repo_updates += 1

            login = str(profile.get("login") or "").strip()
            expected_id = profile.get("github_id")
            eligible = [repo for repo in saved_repos if isinstance(repo, dict) and _repo_is_checkable(repo)]
            eligible.sort(key=lambda repo: (
                int(repo.get("stars") or 0),
                str(repo.get("pushed_at") or repo.get("updated_at") or ""),
            ), reverse=True)
            for repo in eligible[:MAX_AUTHORSHIP_CHECKS_PER_PROFILE]:
                metadata = by_url.get(_canonical_url(str(repo.get("url") or "")))
                if metadata and login:
                    author_jobs.append((profile_id, repo, metadata, login, int(expected_id) if expected_id is not None else None))

        author_results: dict[int, tuple[str, int | None]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(_author_commit, api_repo, login, github_id): index
                for index, (_pid, _repo, api_repo, login, github_id) in enumerate(author_jobs)
            }
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                author_results[futures[future]] = future.result()
                if index % 25 == 0 or index == len(futures):
                    print(f"Commit-authority checks completed: {index}/{len(futures)}.", flush=True)

        confirmed = 0
        checked = 0
        for index, (profile_id, repo, _api_repo, _login, _github_id) in enumerate(author_jobs):
            status, author_id = author_results.get(index, ("unavailable", None))
            repo["authorship_check_status"] = status
            repo["authorship_checked_at"] = now
            if status == "confirmed_by_commit_author_id":
                repo["authored_by_candidate"] = True
                repo["verified_commit_author_id"] = author_id
                confirmed += 1
            else:
                # Lack of a matching linked GitHub author is not proof that the
                # candidate made no contribution, so leave the boolean unset.
                repo.pop("authored_by_candidate", None)
                repo.pop("verified_commit_author_id", None)
            checked += 1

        connection.execute("BEGIN IMMEDIATE")
        for item in profiles:
            connection.execute(
                "UPDATE candidate_profiles SET profile_json=?,updated_at=? WHERE profile_id=?",
                (json.dumps(item["profile"], ensure_ascii=False), now, item["profile_id"]),
            )
        connection.commit()

        report = ROOT / "data" / "evaluation" / "repository_evidence_enrichment.txt"
        report.write_text(
            "GitHub repository evidence enrichment\n"
            f"Checked profiles: {len(profiles)}\n"
            f"Account repo-list requests succeeded: {accounts_ok}/{len(profiles)}\n"
            f"Existing repo rows matched and updated with fork/size/pushed_at: {repo_updates}\n"
            f"Commit authorship checks attempted (up to {MAX_AUTHORSHIP_CHECKS_PER_PROFILE} per profile): {checked}\n"
            f"Commit authorship confirmed by stable GitHub account ID: {confirmed}\n"
            "Unmatched or failed commit checks remain unverified; they are not treated as proof of no authorship.\n"
            f"Database backup: {backup_path}\n",
            encoding="utf-8",
        )
        print(f"Account lists: {accounts_ok}/{len(profiles)}; repo rows updated: {repo_updates}.", flush=True)
        print(f"Authorship checks: {checked}; confirmed by GitHub ID: {confirmed}.", flush=True)
        print(f"Backup: {backup_path}", flush=True)
        print(f"Report: {report}", flush=True)
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
