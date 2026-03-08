import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

from .config import load_config
from .github_api import fetch_starred_repos
from .github_web import GitHubWebClient
from .llm import categorize_repos
from .models import StarList

console = Console()


def print_categorization(
    assignments_by_list: dict[str, list[str]],
    new_lists: list[str],
    existing_names: set[str],
) -> None:
    """Display categorization results as a rich table."""
    table = Table(title="Categorization Result", show_lines=True)
    table.add_column("List", style="bold cyan")
    table.add_column("Status", style="dim")
    table.add_column("Repos")

    for list_name in sorted(assignments_by_list):
        repos = assignments_by_list[list_name]
        status = "[green]existing[/green]" if list_name in existing_names else "[yellow]new[/yellow]"
        table.add_row(list_name, status, "\n".join(repos))

    console.print(table)


async def run(dry_run: bool = False, config_path: Path | None = None) -> None:
    cfg = load_config(config_path)

    # Step 1: Fetch starred repos
    console.print("[bold]Step 1:[/bold] Fetching starred repos...")
    repos = await fetch_starred_repos(cfg.github)
    if not repos:
        console.print("[red]No starred repos found.[/red]")
        return

    # Step 2: Fetch existing lists via web API
    console.print("[bold]Step 2:[/bold] Fetching existing star lists...")
    web = GitHubWebClient(cfg.github)
    try:
        existing_lists = await web.get_lists(repos[0])
        console.print(f"  Found {len(existing_lists)} existing lists.")
        for sl in existing_lists:
            console.print(f"    - {sl.name}")

        # Step 3: LLM categorization
        console.print("[bold]Step 3:[/bold] Categorizing with LLM...")
        result = await categorize_repos(cfg.llm, repos, existing_lists)

        # Group assignments by list
        assignments_by_list: dict[str, list[str]] = defaultdict(list)
        for a in result.assignments:
            assignments_by_list[a.list_name].append(a.repo)

        existing_names = {sl.name for sl in existing_lists}
        print_categorization(assignments_by_list, result.new_lists, existing_names)

        if dry_run:
            console.print("[yellow]Dry run mode - no changes applied.[/yellow]")
            return

        # Confirm with user
        console.print()
        answer = console.input("[bold]Apply these changes? (y/N): [/bold]").strip().lower()
        if answer != "y":
            console.print("Aborted.")
            return

        # Step 4: Execute changes
        console.print("[bold]Step 4:[/bold] Applying changes...")

        # 4a. Create new lists
        list_name_to_id: dict[str, str] = {sl.name: sl.id for sl in existing_lists}

        if result.new_lists:
            console.print(f"  Creating {len(result.new_lists)} new list(s)...")
            for name in result.new_lists:
                new_list = await web.create_list(name, repos[0])
                if new_list:
                    list_name_to_id[new_list.name] = new_list.id
                    console.print(f"    [green]Created:[/green] {name}")
                else:
                    console.print(f"    [red]Failed:[/red] {name}")

        # 4b. Assign repos to lists
        repo_by_name = {r.full_name: r for r in repos}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("Assigning repos...", total=len(result.assignments))

            for a in result.assignments:
                repo = repo_by_name.get(a.repo)
                if not repo:
                    console.print(f"  [yellow]Repo not found: {a.repo}[/yellow]")
                    progress.advance(task)
                    continue

                target_id = list_name_to_id.get(a.list_name)
                if not target_id:
                    console.print(f"  [yellow]List ID not found for: {a.list_name}[/yellow]")
                    progress.advance(task)
                    continue

                ok = await web.assign_repo(repo, [target_id], repos[0])
                if not ok:
                    console.print(f"  [red]Failed to assign {a.repo} → {a.list_name}[/red]")
                progress.advance(task)

        console.print("[bold green]Done![/bold green]")

    finally:
        await web.close()


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    config_path = None

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--config" and i < len(sys.argv) - 1:
            config_path = Path(sys.argv[i + 1])

    asyncio.run(run(dry_run=dry_run, config_path=config_path))


if __name__ == "__main__":
    main()
