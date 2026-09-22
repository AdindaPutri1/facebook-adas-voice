"""Lightweight, best-effort noise filter applied DURING scraping.

Drops obvious ad / sales / spam / contact / clearly-foreign text before it
enters the raw dataset. Conservative by design: only text with a strong noise
signal is dropped; anything ambiguous is kept so the LLM cleaning stage can
decide later. This filter is a heuristic, never a guarantee, and performs no
stealth/evasion of platform protections.

Design:
- STRONG markers drop unconditionally: explicit rental/sales phrases,
  clearly-foreign text, truncation-marker-only blobs, emoji-only comments.
- WEAK sales vocabulary (>= 2 distinct words such as jual/dp/promo) drops.
- Contact/marketplace hits are ambiguous on their own: dropped only for a
  short (link/phone) post or when another ad signal is present.
"""
import re
from typing import Tuple, List

_PHONE_RE = re.compile(
    r"(\+?\s?62[\s\-()]*\d{7,14}|08\d{2}[\s\-]?\d{3,}[\s\-]?\d{3,}|"
    r"0\d{2}[-\s]?\d{7,8}|\d{4}[\s-]\d{4}[\s-]\d{4})"
)
_WHATSAPP_RE = re.compile(r"wa(tsapp)?\s*[.:]?\s*\d+", re.IGNORECASE)
_MARKETPLACE_RE = re.compile(
    r"shopee|tokopedia|lazada|blibli|bukalapak|olx\.co|s\.shopee|tiktok(shop|\.com|videos)"
    r"|carmudi|mobil123|otobloxl|seva\.id|beraniuang|gadgetren",
    re.IGNORECASE,
)

# Phrases that almost never appear in a genuine ADAS customer-voice discussion
# about behaviour. One hit drops the record.
_STRONG_AD_PHRASES = [
    "ready sewa", "sewa mobil", "sewa motor", "rental mobil", "rental motor",
    "mobil rental", "harga sewa", "sewa mulai", "kami menerima jasa",
    "jasa pasang", "langsung pasang", "boleh chat", "chat wa", "chat whatsapp",
    "order sekarang", "pesan sekarang", "stok terbatas", "promo bulan ini",
    "cashback", "gratis ongkir", "harga mulai dari", "freeshipping",
    "pricelist", "harga rusak", "dapatkan sekarang", "itu link", "klik link",
    "cek link", "link di bio", "link whatsapp", "link penjualan",
    "biode", "pin bbm", "telegram kami", "grup jual beli", "harga terupdate",
    "update harga", "spesifikasi lengkap", "syarat ketentuan berlaku",
    "dijamin original", "garansi toko", "dijamin bergaransi",
    "karpet mobil", "mobil karpet", "ready stok", "cocok untuk",
    "tersedia untuk", "compatible dengan", "plug and play",
    # Sale / for-sale transaction intent -> drop unconditionally.
    "dijual", "dijual cepat", "jual murah", "jual cepat", "mobil dijual",
    "motor dijual", "kendaraan dijual", "sale", "obral", "flash sale",
    "big sale", "diskon", "cashback", "cicilan", "kredit", "angsuran",
    "uang muka", "down payment", "dp ringan", "harga nego", "nego sampe jadi",
    "nego paling murah", "serius buyer", "buyer serius", "laku keras",
    "kuota terbatas", "stok tinggal", "hampir habis", "harga spesial",
    "price drop", "best price", "harga promo", "monthly special",
    "prioritas pembeli", "bisa pinjaman",
]
_STRONG_AD_RE = re.compile(
    "(" + "|".join(re.escape(p) for p in _STRONG_AD_PHRASES) + ")", re.IGNORECASE
)

# Vocabulary that can also occur in genuine talk, needs >= 2 hits.
_WEAK_AD_WORDS = [
    "jual", "dijual", "jualan", "dp", "cicilan", "kredit", "bunga", "promo",
    "diskon", "murah", "gratis", "ongkir", "reseller", "dropship", "agen",
    "konsumen", "branded", "stok barang", "harga", "invoice", "transfer",
    "order", "checkout", "belanja", "komisi", "banner", "brosur",
    "spesial", "hubungi", "antre", "dapatkan", "pesan", "tanya-tanya",
]
_WEAK_AD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _WEAK_AD_WORDS) + r")\b",
    re.IGNORECASE,
)

# Euro/Latin extension characters (Polish, Scandinavian, Iberian, French, ...)
# are a strong signal the text is NOT Indonesian/English.
_ACCENTED_CHARS = re.compile(
    r"[áàâãäéèêëíìîïóòôõöúùûüñçßčžšłńćęśźżøåæđðþčžăâ]"
)
_NON_LATIN_RE = re.compile(r"[^\x00-\x7F]")
_ALNUM_RE = re.compile(r"[a-zA-Z0-9]")

# High-precision foreign-language tokens (Spanish/French/Nordic/Polish/German).
# Deliberately excludes words also common in Indonesian/English to avoid
# false positives. >= 2 distinct hits marks the text as foreign.
_FOREIGN_TOKENS_RE = re.compile(
    r"\b(hola|carro|coche|bien|muy|tres|estoy|tiene|comme|mais|avec|vous|nous|"
    r"c'est|tres|toujours|prouve|defaut|bravo|jeg|det|samme|har|ikke|og|bil|"
    r"bilen|mann|dar|vil|jest|bardzo|przygoda|swoja|moja|moj|zacz|dni|czy|nie|"
    r"und|ich|nicht|der|die|das|mit|sehr|gut|pour|une|des|los|las|una|feliz|"
    r"sans|tout|passe|merci|amigo|gustar|bom|obrigado|muito|caramba)\b",
    re.IGNORECASE,
)

_SEE_MORE_RE = re.compile(r"lihat selengkapnya|see more|lihat semua", re.IGNORECASE)


def _count_distinct(text: str) -> int:
    return len(set(m.group(0) for m in _WEAK_AD_RE.finditer(text)))


def _foreign_token_hits(text: str) -> int:
    return len(set(m.group(0).lower() for m in _FOREIGN_TOKENS_RE.finditer(text)))


def looks_foreign(text: str) -> bool:
    """True when the text is clearly not Indonesian/English.

    Heuristic only: heavy accent clusters, a high share of non-ASCII bytes, or
    high-precision foreign/core-European vocabulary. Conservative — uncertainty
    keeps the text.
    """
    if not text:
        return False
    if len(_ACCENTED_CHARS.findall(text)) >= 2:
        return True
    non_ascii = len(_NON_LATIN_RE.findall(text))
    letters = len(_ALNUM_RE.findall(text))
    if letters and non_ascii / letters > 0.35:
        return True
    if _foreign_token_hits(text) >= 2:
        return True
    return False


def _has_contact(text: str) -> bool:
    return bool(_PHONE_RE.search(text) or _WHATSAPP_RE.search(text))


def _has_marketplace(text: str) -> bool:
    return bool(_MARKETPLACE_RE.search(text))


def scan(text: str) -> Tuple[bool, List[str]]:
    """Return (is_noise, reasons) for a single scraped text."""
    if not text or not text.strip():
        return True, ["empty"]

    lowered = text.lower()

    has_contact = _has_contact(lowered)
    has_marketplace = _has_marketplace(lowered)
    weak_hits = _count_distinct(lowered)
    short = len(_ALNUM_RE.findall(text)) < 25
    content_words = len(re.findall(r"[a-zA-Z]{2,}", lowered))

    reasons: List[str] = []

    # Strong signals drop unconditionally.
    if _STRONG_AD_RE.search(lowered):
        reasons.append("ad_sales")
    if looks_foreign(text):
        reasons.append("foreign_language")
    # Facebook truncation blobs that carry no real content besides the marker.
    stripped = _SEE_MORE_RE.sub("", lowered).strip()
    if _SEE_MORE_RE.search(lowered) and len(stripped.strip(" .,!?;:")) < 6:
        reasons.append("truncation_marker_only")
    # Emoji/sticker-only comments.
    if len(_ALNUM_RE.findall(text)) == 0 and len(text.strip()) <= 8:
        reasons.append("emoji_only")

    # Sales vocabulary clusters (>= 2 distinct words) almost always mean an ad.
    if weak_hits >= 2:
        reasons.append(f"ad_vocabulary({weak_hits})")

    # Contact/marketplace hits are ambiguous on their own: keep a long genuine
    # discussion that merely mentions a platform, drop a link/phone post.
    if has_contact and (content_words <= 6 or weak_hits >= 1):
        reasons.append("contact")
    if has_marketplace and (short or weak_hits >= 1):
        reasons.append("marketplace")

    return bool(reasons), reasons