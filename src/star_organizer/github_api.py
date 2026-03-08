import httpx
from rich.console import Console

from .config import GitHubConfig
from .models import StarredRepo

console = Console()


async def fetch_starred_repos(cfg: GitHubConfig) -> list[StarredRepo]:
    """Fetch all starred repos via GitHub REST API with pagination."""
    repos: list[StarredRepo] = []
    url = "https://api.github.com/user/starred"
    params = {"per_page": "100", "page": "1"}
    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        page = 1
        while True:
            params["page"] = str(page)
            console.print(f"  Fetching starred repos page {page}...")
            resp = await client.get(url, params=params)
            resp.raise_for_status()

            data = resp.json()
            if not data:
                break

            for item in data:
                repos.append(
                    StarredRepo(
                        id=item["id"],
                        full_name=item["full_name"],
                        description=item.get("description") or "",
                        language=item.get("language") or "",
                        topics=item.get("topics") or [],
                        html_url=item["html_url"],
                    )
                )

            # Check Link header for next page
            link = resp.headers.get("link", "")
            if 'rel="next"' not in link:
                break
            page += 1

    console.print(f"  Fetched {len(repos)} starred repos.")
    return repos
