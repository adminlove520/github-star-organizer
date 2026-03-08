import asyncio
import re

import httpx
from bs4 import BeautifulSoup
from rich.console import Console

from .config import GitHubConfig
from .models import StarList, StarredRepo

console = Console()

# Shared headers mimicking a browser request
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _build_cookies(cfg: GitHubConfig) -> dict[str, str]:
    return {"user_session": cfg.user_session}


def _extract_csrf_token(html: str) -> str:
    """Extract authenticity_token from HTML form."""
    soup = BeautifulSoup(html, "html.parser")
    token_input = soup.find("input", {"name": "authenticity_token"})
    if token_input and token_input.get("value"):
        return token_input["value"]
    raise ValueError("Could not find CSRF token in HTML. Session cookie may be expired.")


async def fetch_star_lists(
    client: httpx.AsyncClient,
    cfg: GitHubConfig,
    repo: StarredRepo,
) -> tuple[list[StarList], str]:
    """Fetch existing star lists via the repo's list menu endpoint.

    Returns (lists, csrf_token).
    """
    url = f"https://github.com/{repo.full_name}/lists"
    resp = await client.get(
        url,
        headers={**_BROWSER_HEADERS, "X-Requested-With": "XMLHttpRequest"},
        cookies=_build_cookies(cfg),
    )
    resp.raise_for_status()

    html = resp.text
    csrf_token = _extract_csrf_token(html)

    soup = BeautifulSoup(html, "html.parser")
    lists: list[StarList] = []

    for checkbox in soup.find_all("input", {"type": "checkbox", "name": "list_ids[]"}):
        list_id = checkbox.get("value", "")
        if not list_id:
            continue
        # Find the label text (list name)
        label = checkbox.find_parent("label") or checkbox.find_next("label")
        name = ""
        if label:
            truncate = label.find(class_="Truncate-text")
            name = truncate.get_text(strip=True) if truncate else label.get_text(strip=True)
        if name:
            lists.append(StarList(id=list_id, name=name))

    return lists, csrf_token


async def fetch_repo_current_lists(
    client: httpx.AsyncClient,
    cfg: GitHubConfig,
    repo: StarredRepo,
) -> list[str]:
    """Get list IDs that a repo is currently assigned to."""
    url = f"https://github.com/{repo.full_name}/lists"
    resp = await client.get(
        url,
        headers={**_BROWSER_HEADERS, "X-Requested-With": "XMLHttpRequest"},
        cookies=_build_cookies(cfg),
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    checked_ids: list[str] = []
    for checkbox in soup.find_all("input", {"type": "checkbox", "name": "list_ids[]", "checked": True}):
        val = checkbox.get("value", "")
        if val:
            checked_ids.append(val)
    return checked_ids


async def create_star_list(
    client: httpx.AsyncClient,
    cfg: GitHubConfig,
    name: str,
    csrf_token: str,
    description: str = "",
) -> str | None:
    """Create a new star list. Returns the list slug from redirect URL."""
    url = f"https://github.com/stars/{cfg.username}/lists"
    data = {
        "authenticity_token": csrf_token,
        "user_list[name]": name,
        "user_list[description]": description,
        "user_list[private]": "0",
    }

    resp = await client.post(
        url,
        data=data,
        headers={**_BROWSER_HEADERS},
        cookies=_build_cookies(cfg),
        follow_redirects=False,
    )

    # GitHub redirects to the new list page on success
    if resp.status_code in (301, 302, 303):
        location = resp.headers.get("location", "")
        # Extract slug from URL like /stars/username/lists/list-name
        match = re.search(r"/lists/([^/?]+)", location)
        return match.group(1) if match else None

    # Some versions return 200 with a redirect meta tag
    if resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        meta = soup.find("meta", {"http-equiv": "refresh"})
        if meta:
            content = meta.get("content", "")
            match = re.search(r"/lists/([^/?]+)", content)
            return match.group(1) if match else None

    console.print(f"[yellow]Warning: status {resp.status_code} creating list '{name}': {resp.text[:200]}[/yellow]")
    return None


async def assign_repo_to_lists(
    client: httpx.AsyncClient,
    cfg: GitHubConfig,
    repo: StarredRepo,
    list_ids: list[str],
    csrf_token: str,
) -> bool:
    """Assign a repo to the given lists (PUT semantics - replaces all assignments)."""
    url = f"https://github.com/{repo.full_name}/lists"

    # Build form data: empty list_ids[] first, then actual IDs
    # This is required by GitHub's web API
    form_parts = [
        ("_method", "put"),
        ("authenticity_token", csrf_token),
        ("repository_id", str(repo.id)),
        ("context", "user_list_menu"),
        ("list_ids[]", ""),  # Empty value required
    ]
    for lid in list_ids:
        form_parts.append(("list_ids[]", lid))

    resp = await client.post(
        url,
        data=form_parts,
        headers={
            **_BROWSER_HEADERS,
            "X-Requested-With": "XMLHttpRequest",
        },
        cookies=_build_cookies(cfg),
    )

    if resp.status_code in (200, 302):
        return True

    console.print(f"[yellow]Warning: Failed to assign {repo.full_name}, status {resp.status_code}[/yellow]")
    return False


class GitHubWebClient:
    """High-level wrapper managing CSRF tokens and rate limiting."""

    def __init__(self, cfg: GitHubConfig):
        self.cfg = cfg
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._csrf_token: str | None = None
        self._lists: list[StarList] = []
        self._delay = 0.8  # seconds between web API calls

    async def close(self) -> None:
        await self.client.aclose()

    async def get_lists(self, any_repo: StarredRepo) -> list[StarList]:
        """Fetch star lists, caching the CSRF token."""
        self._lists, self._csrf_token = await fetch_star_lists(
            self.client, self.cfg, any_repo
        )
        return self._lists

    async def refresh_csrf(self, any_repo: StarredRepo) -> str:
        """Re-fetch CSRF token (they expire)."""
        _, self._csrf_token = await fetch_star_lists(
            self.client, self.cfg, any_repo
        )
        return self._csrf_token

    async def create_list(self, name: str, any_repo: StarredRepo) -> StarList | None:
        """Create a list and return it with its ID. Refreshes CSRF before each call."""
        # Always refresh CSRF — token is single-use for POST
        await self.refresh_csrf(any_repo)

        slug = await create_star_list(
            self.client, self.cfg, name, self._csrf_token or ""
        )
        await asyncio.sleep(self._delay)

        if slug is None:
            return None

        # Re-fetch lists to get the new list's ID + fresh CSRF
        self._lists, self._csrf_token = await fetch_star_lists(
            self.client, self.cfg, any_repo
        )
        for sl in self._lists:
            if sl.name == name:
                return sl

        console.print(f"[yellow]Created list '{name}' but couldn't find its ID[/yellow]")
        return None

    async def assign_repo(
        self, repo: StarredRepo, target_list_ids: list[str], any_repo: StarredRepo
    ) -> bool:
        """Assign repo to lists, merging with existing assignments for idempotency."""
        # Get current assignments + fresh CSRF from this GET
        current_ids = await fetch_repo_current_lists(self.client, self.cfg, repo)
        await asyncio.sleep(self._delay)

        merged = list(set(current_ids) | set(target_list_ids))

        # Refresh CSRF before POST
        await self.refresh_csrf(any_repo)

        result = await assign_repo_to_lists(
            self.client, self.cfg, repo, merged, self._csrf_token or ""
        )
        await asyncio.sleep(self._delay)
        return result
