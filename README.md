# GitHub Star Organizer

Automatically categorize your GitHub starred repos into Star Lists using LLM.

GitHub's official API doesn't support Star Lists — this tool uses reverse-engineered web APIs (session cookie + CSRF token) to create lists and assign repos.

## How it works

1. Fetch all your starred repos via GitHub REST API
2. Fetch existing Star Lists via GitHub web API
3. Send repo metadata to an LLM for categorization
4. Create new lists and assign repos accordingly

Results are cached locally — re-runs only categorize newly starred repos.

## Setup

```bash
uv sync
cp config.example.toml config.toml
```

Edit `config.toml`:

```toml
[github]
username = "your-username"
token = "ghp_xxxx"                    # GitHub personal access token

[github.session]
# Full cookie string from browser DevTools
cookies = "_octo=...; user_session=...; logged_in=yes; ..."

concurrency = 5                       # GitHub web API concurrency

[llm]
base_url = "https://api.openai.com/v1"
api_key = "sk-xxxx"
model = "gpt-4o"
concurrency = 3                       # Max concurrent LLM batch requests
```

### Getting cookies

1. Open [github.com](https://github.com) in your browser
2. DevTools (F12) → Network tab → any `github.com` request → Headers → Cookie
3. Copy the full cookie string

> Note: Session cookies expire periodically. Refresh if you get CSRF or 403 errors.

## Usage

```bash
# Preview categorization without making changes
uv run python -m star_organizer --dry-run

# Run and apply changes (will ask for confirmation)
uv run python -m star_organizer

# Skip cache (re-fetch repos & re-categorize)
uv run python -m star_organizer --no-cache

# Enable debug output for GitHub web API calls
uv run python -m star_organizer --debug

# Use a custom config path
uv run python -m star_organizer --config path/to/config.toml
```

## License

MIT
