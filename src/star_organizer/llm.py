import json

from openai import AsyncOpenAI
from rich.console import Console

from .config import LLMConfig
from .models import Assignment, CategorizationResult, StarList, StarredRepo

console = Console()

SYSTEM_PROMPT = """You are a GitHub repository organizer. Your job is to categorize starred repositories into meaningful lists.

Rules:
1. Prefer reusing existing lists when appropriate.
2. Create new lists only when no existing list fits well.
3. Each repo should be assigned to exactly ONE list (the best fit).
4. List names should be concise and descriptive (e.g., "AI/ML Tools", "Vue Ecosystem", "CLI Utilities").
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


async def categorize_repos(
    cfg: LLMConfig,
    repos: list[StarredRepo],
    existing_lists: list[StarList],
) -> CategorizationResult:
    """Use LLM to categorize repos into lists. Batches if needed."""
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    all_assignments: list[Assignment] = []
    all_new_lists: set[str] = set()

    # Accumulate list names across batches so LLM sees previously created ones
    known_list_names = {sl.name for sl in existing_lists}

    batches = [repos[i : i + BATCH_SIZE] for i in range(0, len(repos), BATCH_SIZE)]
    console.print(f"  Processing {len(repos)} repos in {len(batches)} batch(es)...")

    for batch_idx, batch in enumerate(batches):
        console.print(f"  Batch {batch_idx + 1}/{len(batches)} ({len(batch)} repos)...")

        # Build fake StarList objects for new lists from prior batches
        all_lists_for_prompt = list(existing_lists) + [
            StarList(id="", name=n) for n in all_new_lists
        ]

        prompt = USER_PROMPT_TEMPLATE.format(
            existing_lists=_build_existing_lists(all_lists_for_prompt),
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

        for a in data.get("assignments", []):
            all_assignments.append(Assignment(repo=a["repo"], list_name=a["list"]))

        for new_name in data.get("new_lists", []):
            if new_name not in known_list_names:
                all_new_lists.add(new_name)
                known_list_names.add(new_name)

    return CategorizationResult(
        assignments=all_assignments,
        new_lists=sorted(all_new_lists),
    )
