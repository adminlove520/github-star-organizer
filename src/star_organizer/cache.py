import json
import time
from dataclasses import asdict
from pathlib import Path

from .models import Assignment, CategorizationResult, StarredRepo

CACHE_DIR = Path(".cache")
CACHE_TTL = 3600 * 6  # 6 hours


def _stars_path(username: str) -> Path:
    return CACHE_DIR / f"stars_{username}.json"


def _llm_path(username: str) -> Path:
    return CACHE_DIR / f"llm_{username}.json"


# ── Starred repos cache ──


def load_cached_repos(username: str) -> list[StarredRepo] | None:
    """Load cached repos if fresh enough, otherwise return None."""
    path = _stars_path(username)
    if not path.exists():
        return None

    data = json.loads(path.read_text())
    if time.time() - data.get("timestamp", 0) > CACHE_TTL:
        return None

    return [
        StarredRepo(
            id=r["id"],
            full_name=r["full_name"],
            description=r["description"],
            language=r["language"],
            topics=r["topics"],
            html_url=r["html_url"],
        )
        for r in data["repos"]
    ]


def save_cached_repos(username: str, repos: list[StarredRepo]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    data = {
        "timestamp": time.time(),
        "username": username,
        "repos": [asdict(r) for r in repos],
    }
    _stars_path(username).write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── LLM categorization cache ──


def load_cached_assignments(username: str) -> dict[str, str] | None:
    """Load cached repo→list assignments. Returns {full_name: list_name} or None."""
    path = _llm_path(username)
    if not path.exists():
        return None

    data = json.loads(path.read_text())
    return data.get("assignments")  # {full_name: list_name}


def save_cached_assignments(username: str, result: CategorizationResult) -> None:
    """Persist LLM assignments as {full_name: list_name} map."""
    CACHE_DIR.mkdir(exist_ok=True)
    mapping = {a.repo: a.list_name for a in result.assignments}
    data = {
        "timestamp": time.time(),
        "username": username,
        "assignments": mapping,
    }
    _llm_path(username).write_text(json.dumps(data, ensure_ascii=False, indent=2))


def merge_cached_assignments(
    cached: dict[str, str],
    new_result: CategorizationResult,
    all_repo_names: set[str],
) -> CategorizationResult:
    """Merge cached assignments with new LLM results.

    - New results override cached for the same repo
    - Cached entries for repos no longer starred are dropped
    """
    merged: dict[str, str] = {}

    # Start with cached, filtered to still-starred repos
    for repo, list_name in cached.items():
        if repo in all_repo_names:
            merged[repo] = list_name

    # Override/add with new LLM results
    for a in new_result.assignments:
        merged[a.repo] = a.list_name

    # Collect all unique list names to figure out which are "new"
    all_list_names = set(merged.values())
    # new_lists from the fresh LLM call are authoritative
    new_lists = list(new_result.new_lists)

    return CategorizationResult(
        assignments=[Assignment(repo=r, list_name=l) for r, l in merged.items()],
        new_lists=new_lists,
    )
