import asyncio
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table

from .cache import (
    load_cached_repos,
    save_cached_repos,
    load_cached_assignments,
    save_cached_assignments,
    merge_cached_assignments,
)
from .config import load_config
from .github_api import fetch_starred_repos
from .github_web import GitHubWebClient, enable_debug
from .llm import categorize_repos

console = Console()


@contextmanager
def timed_status(label: str, **kwargs):
    """Spinner with elapsed time printed on completion."""
    t0 = time.monotonic()
    with console.status(f"[bold]{label}...", spinner="dots", **kwargs) as status:
        yield status
    elapsed = time.monotonic() - t0
    console.print(f"[green]✓[/green] {label} [dim]({elapsed:.1f}s)[/dim]")


def print_categorization(
    assignments_by_list: dict[str, list[str]],
    existing_names: set[str],
) -> None:
    table = Table(title="Categorization Result", show_lines=True)
    table.add_column("List", style="bold cyan")
    table.add_column("Status", style="dim")
    table.add_column("Repos")

    for list_name in sorted(assignments_by_list):
        repos = assignments_by_list[list_name]
        status = "[green]existing[/green]" if list_name in existing_names else "[yellow]new[/yellow]"
        table.add_row(list_name, status, "\n".join(repos))

    console.print(table)


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn("dots"),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


async def run(dry_run: bool = False, no_cache: bool = False, config_path: Path | None = None) -> None:
    cfg = load_config(config_path)
    t_total = time.monotonic()

    # Step 1: Fetch starred repos
    repos = None if no_cache else load_cached_repos(cfg.github.username)
    if repos:
        console.print(f"[green]✓[/green] Loaded {len(repos)} repos from cache [dim]({cfg.github.username})[/dim]")
    else:
        with timed_status("Fetching starred repos") as status:
            def on_page(page: int, count: int) -> None:
                status.update(f"[bold]Fetching starred repos... [dim]page {page}, {count} repos[/dim]")

            repos = await fetch_starred_repos(cfg.github, on_page=on_page)
            if repos:
                save_cached_repos(cfg.github.username, repos)

    if not repos:
        console.print("[red]No starred repos found.[/red]")
        return

    # Step 2: Fetch existing lists
    web = GitHubWebClient(cfg.github)
    try:
        with timed_status("Fetching star lists"):
            existing_lists = await web.get_lists(repos[0])

        if existing_lists:
            for sl in existing_lists:
                console.print(f"  [dim]-[/dim] {sl.name}")
        else:
            console.print("  [dim]No existing lists.[/dim]")

        # Step 3: LLM categorization (incremental — only new repos)
        cached_assignments = None if no_cache else load_cached_assignments(cfg.github.username)
        if cached_assignments:
            new_repos = [r for r in repos if r.full_name not in cached_assignments]
            console.print(
                f"[green]✓[/green] LLM cache hit: {len(cached_assignments)} repos cached, "
                f"{len(new_repos)} new to categorize"
            )
        else:
            new_repos = repos

        if new_repos:
            with timed_status("Categorizing with LLM") as status:
                def on_batch(idx: int, total: int, count: int) -> None:
                    status.update(f"[bold]Categorizing with LLM... [dim]batch {idx}/{total} ({count} repos)[/dim]")

                new_result = await categorize_repos(cfg.llm, new_repos, existing_lists, on_batch=on_batch)

            if cached_assignments:
                all_repo_names = {r.full_name for r in repos}
                result = merge_cached_assignments(cached_assignments, new_result, all_repo_names)
            else:
                result = new_result

            save_cached_assignments(cfg.github.username, result)
        else:
            # All repos already cached, reconstruct result from cache
            from .models import Assignment, CategorizationResult
            result = CategorizationResult(
                assignments=[Assignment(repo=r, list_name=l) for r, l in cached_assignments.items()
                             if r in {repo.full_name for repo in repos}],
                new_lists=[],
            )
            console.print("[green]✓[/green] All repos already categorized [dim](skipped LLM)[/dim]")

        # Display results
        assignments_by_list: dict[str, list[str]] = defaultdict(list)
        for a in result.assignments:
            assignments_by_list[a.list_name].append(a.repo)

        existing_names = {sl.name for sl in existing_lists}
        print_categorization(assignments_by_list, existing_names)

        if dry_run:
            console.print("[yellow]Dry run - no changes applied.[/yellow]")
            return

        console.print()
        if console.input("[bold]Apply these changes? (y/N): [/bold]").strip().lower() != "y":
            console.print("Aborted.")
            return

        # Step 4: Execute
        list_name_to_id: dict[str, str] = {sl.name: sl.id for sl in existing_lists}

        # 4a. Create new lists
        if result.new_lists:
            with _make_progress() as progress:
                task = progress.add_task("Creating lists...", total=len(result.new_lists))
                for name in result.new_lists:
                    progress.update(task, description=f"Creating list: {name}")
                    new_list = await web.create_list(name, repos[0])
                    if new_list:
                        list_name_to_id[new_list.name] = new_list.id
                    else:
                        console.print(f"  [red]Failed to create: {name}[/red]")
                    progress.advance(task)

        # 4b. Assign repos
        repo_by_name = {r.full_name: r for r in repos}

        with _make_progress() as progress:
            task = progress.add_task("Assigning repos...", total=len(result.assignments))

            for a in result.assignments:
                repo = repo_by_name.get(a.repo)
                if not repo:
                    progress.advance(task)
                    continue

                target_id = list_name_to_id.get(a.list_name)
                if not target_id:
                    progress.advance(task)
                    continue

                progress.update(task, description=f"Assigning {a.repo} → {a.list_name}")
                ok = await web.assign_repo(repo, [target_id])
                if not ok:
                    console.print(f"  [red]Failed: {a.repo} → {a.list_name}[/red]")
                progress.advance(task)

        elapsed_total = time.monotonic() - t_total
        console.print(f"[bold green]Done![/bold green] [dim]Total: {elapsed_total:.1f}s[/dim]")

    finally:
        await web.close()


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    no_cache = "--no-cache" in sys.argv
    config_path = None

    if "--debug" in sys.argv:
        enable_debug()

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--config" and i < len(sys.argv) - 1:
            config_path = Path(sys.argv[i + 1])

    asyncio.run(run(dry_run=dry_run, no_cache=no_cache, config_path=config_path))


if __name__ == "__main__":
    main()
