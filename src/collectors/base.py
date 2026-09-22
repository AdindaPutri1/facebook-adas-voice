import abc
from typing import Iterable, List, Dict, Optional

from src.models import RawRecord


class CollectorError(Exception):
    """Generic collector error."""


class TemporaryNetworkError(CollectorError):
    pass


class PageUnavailableError(CollectorError):
    pass


class AuthenticationError(CollectorError):
    pass


class ParserError(CollectorError):
    pass


class UnexpectedPageStructureError(CollectorError):
    pass


class EmptyResultError(CollectorError):
    pass


class DuplicateError(CollectorError):
    pass


class BaseCollector(abc.ABC):
    """Interface for any compatible data source (Facebook, mock, API adapter)."""

    data_source = "base"

    def __init__(self, config: Dict):
        self.config = config
        self.retry_max = int(config.get("retry_max", 3))
        self.retry_backoff = float(config.get("retry_backoff_base_seconds", 2))

    @abc.abstractmethod
    def iter_posts(self, community: Dict) -> Iterable[Dict]:
        """Yield raw post dicts in a bounded, resumable manner."""

    @abc.abstractmethod
    def iter_comments(self, post: Dict) -> Iterable[Dict]:
        """Yield comment dicts for a post."""

    @abc.abstractmethod
    def iter_replies(self, comment: Dict) -> Iterable[Dict]:
        """Yield reply dicts for a comment."""

    @abc.abstractmethod
    def close(self) -> None:
        pass

    def check_access(self) -> None:
        """Raise if the platform refuses legitimate automated access."""
        return None


def normalize_community(community: Dict) -> Dict:
    out = dict(community)
    for key in ("name", "community_name"):
        if out.get(key):
            out["community_name"] = out[key]
    out.setdefault("community_name", out.get("name", "unknown"))
    return out