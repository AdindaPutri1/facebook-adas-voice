"""Relevance screening.

Distinguishes relevant / not_relevant / uncertain.
Keyword presence is NOT evidence of relevance.

Heuristics (rule-based, documented):
- Question syntax -> relevant but evidence_type='question'
- Spec announcements ("punya X fitur ADAS", "sudah ada fitur X") -> low-information
  but can still be 'relevant' with evidence_type='specification'.
- Experience signals (past tense, first-person, evaluative adjectives about
  behaviour) -> relevant.
- Pure off-topic posts without any ADAS-system behavioural context -> not_relevant.

The system never claims a keyword hit is automatically a customer experience.
"""
import re
import logging
from typing import Dict, List

log = logging.getLogger(__name__)

_QUESTION_MARKERS = re.compile(
    r"(\?|apakah\b|bagaimana\b|berapa\b|kenapa\b|ngapain\b|kapan\b|dimana\b|di mana\b|"
    r"\bnggak\b|\bngga\b|\bkagak\b|\bgak\b|\bnggk\b|"
    r"bisa\s+\w+\s+(nggak|ngga|gak|g)\b|\bada yang tau\b|\bada yang tahu\b|"
    r"cara\s+(setel|setting|atur|ngatur|pasang)\b)",
    re.IGNORECASE,
)
_SPEC_MARKERS = re.compile(
    r"(punya \d+ fitur|jumlah fitur|spesifikasi|tertera|brosur|manual book)\w*",
    re.IGNORECASE,
)
_HEARSAY_MARKERS = re.compile(
    r"(katanya|kata teman|kata dealer|dengar|kabarnya|menurut orang)", re.IGNORECASE
)
_OPINION_MARKERS = re.compile(
    r"(menurut saya|menurutku|menurut gue|kayaknya|sepertinya|aku rasa|gue rasa)\w*",
    re.IGNORECASE,
)
_EXPERIENCE_MARKERS = re.compile(
    r"(ku coba|sudah (saya|aku|gue) (coba|pakai)|saya sudah|coba langsung|kemarin (saya|aku)|"
    r"waktu (saya|aku) pakai|punya saya|unit (saya|ku)|saya alami|aku alami|"
    r"tadi (saya|aku) pakai|setelah dipakai|punya ku|sudah diaplikasi|"
    r"[sp]ernah (saya|aku|gue)? ?(ngalamin|ngalami|mengalami|coba|nyoba)|"
    r"sudah kucoba|sudah kalahkan|langsung saya rasakan)",
    re.IGNORECASE,
)


def _experiment():
    return False


def classify_relevance(text: str, matched_features: List[str], keyword_candidate: bool) -> str:
    """Return 'relevant' | 'not_relevant' | 'uncertain'."""
    lowered = text.lower()
    if not keyword_candidate and not matched_features:
        return "not_relevant"

    is_question = bool(_QUESTION_MARKERS.search(lowered))
    is_spec = bool(_SPEC_MARKERS.search(lowered))
    is_hearsay = bool(_HEARSAY_MARKERS.search(lowered))
    is_opinion = bool(_OPINION_MARKERS.search(lowered))
    is_experience = bool(_EXPERIENCE_MARKERS.search(lowered))

    if is_question or is_hearsay or is_opinion or is_spec:
        # Still relevant to customer-voice pipeline (can be a question about ACC etc.)
        return "relevant"
    if is_experience:
        return "relevant"

    # Behavioural context: something is being said about how the system behaves
    behavioural = bool(
        re.search(
            r"(ngerem|rem|akseleras|ikut|follow|jarak|gas|setir|nyentak|halus|jedug|mendadak|"
            r"brake|lambat|cepat|deselerasi|deceler|maksa|stop|cruise|response|respon)",
            lowered,
            re.IGNORECASE,
        )
    )
    if behavioural and len(lowered.split()) >= 6:
        return "relevant"

    return "uncertain"


def classify_evidence(text: str) -> str:
    """evidence_type: direct_experience | opinion | question | hearsay |
    specification | uncertain."""
    lowered = text.lower()
    if _QUESTION_MARKERS.search(lowered):
        return "question"
    if _HEARSAY_MARKERS.search(lowered):
        return "hearsay"
    if _SPEC_MARKERS.search(lowered):
        return "specification"
    if _OPINION_MARKERS.search(lowered):
        return "opinion"
    if _EXPERIENCE_MARKERS.search(lowered):
        return "direct_experience"
    # First-person + past behaviour about a system -> likely direct experience
    if re.search(
        r"(saya|aku|gue|gw).{0,40}(coba|pakai|nyoba|pak|sudah|kemarin|tadi|mengalami|jalan)",
        lowered,
        re.IGNORECASE,
    ):
        return "direct_experience"
    return "uncertain"