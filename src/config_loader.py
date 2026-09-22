import os
from typing import Any, Dict
from functools import lru_cache

import yaml


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")


def load_dotenv_simple(path: str = None) -> None:
    """Minimal .env loader (no external dependency). Real values only; never logged."""
    path = path or os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                os.environ.setdefault(key, value)


load_dotenv_simple()


def _load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_yaml(path: str) -> Dict[str, Any]:
    return _load_yaml(path)


@lru_cache(maxsize=8)
def load_settings():
    return _load_yaml(os.path.join(CONFIG_DIR, "settings.yaml"))


@lru_cache(maxsize=8)
def load_vehicles():
    return _load_yaml(os.path.join(CONFIG_DIR, "vehicles.yaml"))


@lru_cache(maxsize=8)
def load_keywords():
    return _load_yaml(os.path.join(CONFIG_DIR, "keywords.yaml"))


@lru_cache(maxsize=8)
def load_taxonomy():
    return _load_yaml(os.path.join(CONFIG_DIR, "taxonomy.yaml"))


@lru_cache(maxsize=8)
def load_communities():
    return _load_yaml(os.path.join(CONFIG_DIR, "communities.yaml"))


def resolve_path(path_key: str) -> str:
    """Resolve a configured path, possibly relative to project root."""
    settings = load_settings()
    paths = settings.get("paths", {})
    val = paths.get(path_key, path_key)
    if not os.path.isabs(val):
        val = os.path.join(PROJECT_ROOT, val)
    return val


def ensure_dirs() -> None:
    settings = load_settings()
    paths = settings.get("paths", {})
    for key, val in paths.items():
        if not os.path.isabs(val):
            val = os.path.join(PROJECT_ROOT, val)
        os.makedirs(val, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)


def config_info() -> Dict[str, str]:
    settings = load_settings().get("project", {})
    return {
        "config_version": settings.get("config_version", "unknown"),
        "keyword_version": settings.get("keyword_version", "unknown"),
        "taxonomy_version": settings.get("taxonomy_version", "unknown"),
        "scraper_version": settings.get("scraper_version", "unknown"),
    }