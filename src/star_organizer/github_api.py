import httpx

from .config import GitHubConfig
from .models import StarredRepo


async def fetch_starred_repos(
    cfg: GitHubConfig,
    on_page: callable = None,
) -> list[StarredRepo]:
    """Fetch all starred repos via GitHub REST API with pagination.

    on_page(page, count_so_far) is called after each page if provided.
    """
    repos: list[StarredRepo] = []
    url = "https://api.github.com/user/starred"
    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        page = 1
        while True:
            resp = await client.get(url, params={"per_page": "100", "page": str(page)})
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

            if on_page:
                on_page(page, len(repos))

            if 'rel="next"' not in resp.headers.get("link", ""):
                break
            page += 1

    return repos
