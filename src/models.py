from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


RAW_FIELDS = [
    "record_id",
    "vehicle",
    "community",
    "community_url",
    "post_id",
    "comment_id",
    "parent_id",
    "source_type",
    "author_pseudonym",
    "date",
    "text_raw",
    "url",
    "scraped_at",
]

CLEAN_FIELDS = [
    "record_id",
    "vehicle",
    "community",
    "post_id",
    "comment_id",
    "parent_id",
    "source_type",
    "date",
    "text_clean",
    "url",
    "scraped_at",
]

LABELED_FIELDS = [
    "record_id",
    "vehicle",
    "feature",
    "subfeature",
    "scenario",
    "experience_summary",
    "sentiment",
    "evidence_type",
    "relevant",
    "expectation_mismatch",
    "smoothness",
    "confidence",
    "keyword_candidate",
    "matched_keywords",
    "source_type",
    "date",
    "community",
    "source_reference",
    "author_pseudonym",
    "labeler",
]

SOURCE_TYPES = ("post", "comment", "reply")
RELEVANCE_VALUES = ("relevant", "not_relevant", "uncertain")
FEATURE_VALUES = (
    "PDA", "ACC", "LCC", "LKA", "LDW", "LDP", "ELK", "AEB", "FCW",
    "DMS", "ALC", "TSR", "BSD", "RCTA", "RCW", "unknown", "both",
)
EVIDENCE_VALUES = (
    "direct_experience",
    "opinion",
    "question",
    "hearsay",
    "specification",
    "uncertain",
)
SENTIMENT_VALUES = ("positive", "negative", "neutral", "mixed", "uncertain")
MISMATCH_VALUES = ("yes", "no", "unclear")
SMOOTHNESS_VALUES = (
    "smooth",
    "slightly_abrupt",
    "abrupt",
    "very_abrupt",
    "not_stated",
)


def utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_record_id(
    community: str,
    post_id: str,
    comment_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    source_type: str = "post",
    url: Optional[str] = None,
) -> str:
    """Deterministic record id for idempotency."""
    parts = [community or "", post_id or "", source_type or ""]
    if source_type == "comment":
        parts.append(comment_id or "")
    if source_type == "reply":
        parts.append(comment_id or "")
        parts.append(parent_id or "")
    if url:
        parts.append(url)
    raw = "|".join(parts).strip("|")
    if not raw:
        from hashlib import md5

        return "rec_" + md5(str(url or str(datetime.now())).encode("utf-8")).hexdigest()[:12]
    from hashlib import md5

    return "rec_" + md5(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class RawRecord:
    vehicle: str
    community: str
    community_url: str
    post_id: str
    comment_id: Optional[str]
    parent_id: Optional[str]
    source_type: str
    author_id: Optional[str]
    author_pseudonym: Optional[str]
    date: Optional[str]
    text_raw: str
    url: Optional[str]
    scraped_at: Optional[str] = None
    record_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.record_id:
            self.record_id = make_record_id(
                community=self.community,
                post_id=self.post_id,
                comment_id=self.comment_id,
                parent_id=self.parent_id,
                source_type=self.source_type,
                url=self.url,
            )
        if not self.scraped_at:
            self.scraped_at = utcnow_str()

    def to_row(self) -> Dict[str, Any]:
        row = asdict(self)
        row.pop("extra", None)
        row["author_id"] = None  # never write raw author id downstream
        return row


@dataclass
class CleanRecord:
    record_id: str
    vehicle: str
    community: str
    post_id: str
    comment_id: Optional[str]
    parent_id: Optional[str]
    source_type: str
    date: Optional[str]
    text_clean: str
    url: Optional[str]
    scraped_at: Optional[str]

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LabeledRecord:
    record_id: str
    vehicle: str
    text_clean: str
    feature: str = "unknown"
    subfeature: str = "not_stated"
    scenario: str = "not_stated"
    experience_summary: str = ""
    sentiment: str = "uncertain"
    evidence_type: str = "uncertain"
    relevant: str = "uncertain"
    expectation_mismatch: str = "unclear"
    smoothness: str = "not_stated"
    confidence: str = "low"
    keyword_candidate: bool = False
    matched_keywords: List[str] = field(default_factory=list)
    source_type: str = "post"
    date: Optional[str] = None
    community: str = ""
    source_reference: str = ""
    author_pseudonym: Optional[str] = None
    labeler: str = "rule"

    def to_row(self) -> Dict[str, Any]:
        return asdict(self)