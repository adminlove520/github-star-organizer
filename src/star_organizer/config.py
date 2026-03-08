import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitHubConfig:
    username: str
    token: str
    user_session: str


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str


@dataclass
class Config:
    github: GitHubConfig
    llm: LLMConfig


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Path("config.toml")

    if not path.exists():
        print(f"Config file not found: {path}")
        print("Copy config.example.toml to config.toml and fill in your credentials.")
        sys.exit(1)

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    gh = raw["github"]
    session = gh.get("session", {})

    return Config(
        github=GitHubConfig(
            username=gh["username"],
            token=gh["token"],
            user_session=session["user_session"],
        ),
        llm=LLMConfig(
            base_url=raw["llm"]["base_url"],
            api_key=raw["llm"]["api_key"],
            model=raw["llm"]["model"],
        ),
    )
