# GitHub Star Organizer

Automatically categorize your GitHub starred repos into Star Lists using LLM.

GitHub's official API doesn't support Star Lists — this tool uses reverse-engineered web APIs (session cookie + CSRF token) to create lists and assign repos.

## How it works

1. Fetch all your starred repos via GitHub REST API
2. Fetch existing Star Lists via GitHub web API
3. Send repo metadata to an LLM for categorization
4. Create new lists and assign repos accordingly

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
user_session = "DVI0kn..."           # Browser DevTools → Cookies → user_session

[llm]
base_url = "https://api.openai.com/v1"
api_key = "sk-xxxx"
model = "gpt-4o"
```

### Getting `user_session`

1. Open [github.com](https://github.com) in your browser
2. DevTools (F12) → Application → Cookies → `github.com`
3. Copy the value of `user_session`

> Note: This cookie expires periodically. Refresh it if you get CSRF errors.

## Usage

```bash
# Preview categorization without making changes
uv run python -m star_organizer --dry-run

# Run and apply changes (will ask for confirmation)
uv run python -m star_organizer

# Use a custom config path
uv run python -m star_organizer --config path/to/config.toml
```

## License

MIT
