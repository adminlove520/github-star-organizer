import asyncio
import json

from openai import AsyncOpenAI

from .config import LLMConfig
from .models import Assignment, CategorizationResult, StarList, StarredRepo

SYSTEM_PROMPT = """You are a GitHub repository organizer. Your job is to categorize starred repositories into meaningful lists.

Rules:
1. Prefer reusing existing lists when appropriate — ALWAYS reuse before creating new.
2. Keep the TOTAL number of lists under 32 (GitHub's hard limit). Use broad categories, not fine-grained ones.
3. Each repo should be assigned to exactly ONE list (the best fit).
4. List names should be concise and broad (e.g., "AI/ML", "Web Frameworks", "DevOps", "CLI Tools"). Avoid overly specific names.
5. Respond ONLY with valid JSON, no markdown fences."""

USER_PROMPT_TEMPLATE = """Here are the existing star lists:
{existing_lists}

Here are the repositories to categorize:
{repo_summaries}

Categorize each repository into a list. Return JSON in this exact format:
{{
  "assignments": [
    {{"repo": "owner/name", "list": "List Name"}},
    ...
  ],
  "new_lists": ["New List 1", ...]
}}

"new_lists" should contain ONLY list names that don't exist yet. Keep list names short and clear."""

BATCH_SIZE = 100


def _build_repo_summaries(repos: list[StarredRepo]) -> str:
    return "\n".join(r.summary() for r in repos)


def _build_existing_lists(lists: list[StarList]) -> str:
    if not lists:
        return "(none yet)"
    return "\n".join(f"- {sl.name}" for sl in lists)


async def _categorize_batch(
    client: AsyncOpenAI,
    cfg: LLMConfig,
    batch: list[StarredRepo],
    existing_lists: list[StarList],
    semaphore: asyncio.Semaphore,
) -> tuple[list[Assignment], set[str]]:
    """Categorize a single batch of repos with concurrency control."""
    async with semaphore:
        prompt = USER_PROMPT_TEMPLATE.format(
            existing_lists=_build_existing_lists(existing_lists),
            repo_summaries=_build_repo_summaries(batch),
        )

        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)

        assignments = [
            Assignment(repo=a["repo"], list_name=a["list"])
            for a in data.get("assignments", [])
        ]
        new_lists = set(data.get("new_lists", []))
        return assignments, new_lists


async def categorize_repos(
    cfg: LLMConfig,
    repos: list[StarredRepo],
    existing_lists: list[StarList],
    on_batch: callable = None,
) -> CategorizationResult:
    """Use LLM to categorize repos into lists with concurrent batch processing.

    on_batch(batch_idx, total_batches, count) is called as batches complete.
    """
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    semaphore = asyncio.Semaphore(cfg.concurrency)

    known_list_names = {sl.name for sl in existing_lists}
    batches = [repos[i : i + BATCH_SIZE] for i in range(0, len(repos), BATCH_SIZE)]

    completed = 0

    async def run_batch(batch_idx: int, batch: list[StarredRepo]):
        nonlocal completed
        result = await _categorize_batch(client, cfg, batch, existing_lists, semaphore)
        completed += 1
        if on_batch:
            on_batch(completed, len(batches), len(batch))
        return result

    results = await asyncio.gather(
        *(run_batch(i, batch) for i, batch in enumerate(batches))
    )

    all_assignments: list[Assignment] = []
    all_new_lists: set[str] = set()
    for assignments, new_lists in results:
        all_assignments.extend(assignments)
        for name in new_lists:
            if name not in known_list_names:
                all_new_lists.add(name)
                known_list_names.add(name)

    return CategorizationResult(
        assignments=all_assignments,
        new_lists=sorted(all_new_lists),
    )
