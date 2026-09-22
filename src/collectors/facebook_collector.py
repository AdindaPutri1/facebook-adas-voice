"""Legitimate Facebook community collector.

Uses an authorized, logged-in browser session (user-supplied cookies file exported
from their own authorized browser). Performs NO stealth/evasion techniques.

If Facebook presents a login wall / checkpoint / CAPTCHA, we log the failure and stop.
We never attempt to bypass platform protections. Selectors are configurable in
config/fb_selectors.json (update there, not in source).
"""
import time
import json
import os
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, List
from urllib.parse import urljoin

from src.collectors.base import (
    BaseCollector,
    AuthenticationError,
    PageUnavailableError,
    ParserError,
    TemporaryNetworkError,
    UnexpectedPageStructureError,
)
from src.collectors.facebook_session import (
    default_cookies_path,
    default_profile_dir,
    is_logged_in,
    page_blocked,
    save_debug_page,
    session_alive,
)
from src.collectors.noise_filter import scan as scan_noise
from src.config_loader import CONFIG_DIR, load_settings

log = logging.getLogger(__name__)

DEFAULT_SELECTORS = {
    "login_required_markers": ["login_dialog", "login.php", "checkpoint"],
    "post_containers": ['div[data-pagelet*="FeedUnit"]', "div[role='article']"],
    "post_containers_alt": ["div[dir='auto']"],
    "post_text": ['div[data-ad-preview="message"]', "div[dir='auto'] span[dir='auto']"],
    "comment_containers": ["div[role='article'] ul li", "div[aria-label*='comment']"],
    "comment_text": ["div[data-testid='UFI2CommentBody']", "div[dir='auto']"],
    "reply_text": ["div[data-testid='UFI2CommentBody']", "div[dir='auto']"],
    "expand_comments": ["a[href*='comment']", "div[aria-label*='comment']"],
    "group_id_hint": ["#groupsTabPagelet", "div[data-pagelet='Group']"],
}


def _load_selectors() -> Dict:
    path = os.path.join(CONFIG_DIR, "fb_selectors.json")
    selectors = {}
    for k, v in DEFAULT_SELECTORS.items():
        selectors[k] = list(v)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            selectors.update(json.load(f))
    return selectors


def _safe_text(el) -> str:
    try:
        return (getattr(el, "text", "") or "").strip()
    except Exception:
        return ""


NOISE_MARKERS = (
    "rb anggota", "postingan per hari", "pengikut", "marketplace",
    "lihat semua", "dealer", "agen", "selamat bergabung",
)
NOISE_HEADER_WORDS = {"grup", "halaman", "marketplace", "acara", "kategori", "pembuat"}


def _is_noise_container(text: str) -> bool:
    """Rule-based filter for non-post containers (group cards, ads).

    NOTE: post action rows ("Balas / Bagikan / ...") are NOT treated as noise on
    their own — real group posts include them inside the container text.
    """
    low = text.lower()
    hits = sum(1 for m in NOISE_MARKERS if m in low)
    if hits >= 2:
        return True
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first_line.strip().lower() in NOISE_HEADER_WORDS


# ── post timestamp heuristics ────────────────────────────────────────────────
# Facebook group feeds render relative timestamps ("3 th", "5 jam", "2 d").
# We convert them into an approximate ISO date so history filters (history_since)
# can be applied at collection time. Full dates ("12 Januari 2022") win over
# relative ones. Anything undetectable is kept anyway (date=None).

_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# (regex, unit) — unit one of minutes/hours/days/weeks/months/years
_RELATIVE_RE = [
    (re.compile(r"(\d+)\s*(?:min|menit|mnt)\b", re.IGNORECASE), "minutes"),
    (re.compile(r"(\d+)\s*(?:jam|hour|hrs?|h)\b", re.IGNORECASE), "hours"),
    (re.compile(r"(\d+)\s*(?:hari|day|d)\b", re.IGNORECASE), "days"),
    (re.compile(r"(\d+)\s*(?:pekan|minggu|week|wk|w)\b", re.IGNORECASE), "weeks"),
    (re.compile(r"(\d+)\s*(?:bulan|bln|month|mo)\b", re.IGNORECASE), "months"),
    (re.compile(r"(\d+)\s*(?:tahun|thn|th|t|year|y)\b", re.IGNORECASE), "years"),
]

_ABBR_MAP = {
    "min": "minutes", "menit": "minutes", "mnt": "minutes",
    "jam": "hours", "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours",
    "hari": "days", "d": "days", "day": "days",
    "pekan": "weeks", "minggu": "weeks", "mgu": "weeks", "w": "weeks", "wk": "weeks",
    "bulan": "months", "bln": "months", "mo": "months",
    "tahun": "years", "thn": "years", "th": "years", "t": "years", "y": "years",
}


def parse_relative_date(text: str, now: Optional[datetime] = None) -> Optional[str]:
    """Parse a Facebook-style relative/full timestamp into an ISO date (YYYY-MM-DD).

    Returns None when nothing recognizable is found.
    """
    if not text:
        return None
    now = now or datetime.now(timezone.utc)

    # Absolute dates, e.g. "12 Januari 2022" / "Jan 12, 2022"
    m = re.search(
        r"(?P<d>\d{1,2})\s+(?P<mo>[A-Za-z]+)[.,]?\s+(?P<y>\d{4})", text)
    if m and m.group("mo").lower() in _MONTHS:
        try:
            return datetime(int(m.group("y")), _MONTHS[m.group("mo").lower()],
                            int(m.group("d"))).date().isoformat()
        except ValueError:
            pass
    m = re.search(
        r"(?P<mo>[A-Za-z]+)[.,]?\s+(?P<d>\d{1,2})[.,]?\s+(?P<y>\d{4})", text)
    if m and m.group("mo").lower() in _MONTHS:
        try:
            return datetime(int(m.group("y")), _MONTHS[m.group("mo").lower()],
                            int(m.group("d"))).date().isoformat()
        except ValueError:
            pass

    # "baru saja" / "just now"
    if re.search(r"\b(baru saja|just now|sekarang)\b", text, re.IGNORECASE):
        return now.date().isoformat()

    # relative amounts
    quantity = None
    unit = None
    for rx, u in _RELATIVE_RE:
        m = rx.search(text)
        if m:
            quantity = int(m.group(1))
            unit = u
            break
    if quantity is None or unit is None:
        # bare abbreviation forms: "3th", "5jam", "2d"
        m = re.search(r"(\d+)\s*([A-Za-z]{1,4})\b", text)
        if m:
            key = m.group(2).lower()
            if key in _ABBR_MAP:
                quantity = int(m.group(1))
                unit = _ABBR_MAP[key]
            else:
                return None
        else:
            return None
    if quantity <= 0:
        return now.date().isoformat()
    if unit == "minutes":
        base = timedelta(minutes=1)
    elif unit == "hours":
        base = timedelta(hours=1)
    elif unit == "days":
        base = timedelta(days=1)
    elif unit == "weeks":
        base = timedelta(weeks=1)
    elif unit == "months":
        base = timedelta(days=30)
    else:  # years
        base = timedelta(days=365)
    return (now - base * quantity).date().isoformat()


def _extract_post_date(post_el, fallback_text: str = None) -> Optional[str]:
    """Best-effort post timestamp from a feed container.

    Looks for abbr[data-utime] (Facebook uses epoch-ms there) or an anchor whose
    text is a time label ("2 hari", "3 th", "Jan 12, 2022"). Fallback to the raw
    container text when the DOM hints are absent.
    """
    candidates = []
    try:
        for abbr in post_el.find_elements("xpath", ".//abbr[@data-utime]"):
            ut = abbr.get_attribute("data-utime")
            try:
                ms = int(ut)
                if ms and ms > 0:
                    candidates.append(datetime.fromtimestamp(ms / 1000,
                                                             tz=timezone.utc).date().isoformat())
            except (TypeError, ValueError, OSError):
                pass
    except Exception:
        pass
    # Modern FB puts the short label in aria-label / tooltip attributes rather
    # than visible text. Probe them before the visible anchor text.
    try:
        for el in post_el.find_elements("xpath", ".//*[@aria-label]"):
            for attr in ("aria-label", "title", "data-tooltip-content"):
                val = (el.get_attribute(attr) or "").strip()
                if val and parse_relative_date(val):
                    candidates.append(parse_relative_date(val))
    except Exception:
        pass
    try:
        for a in post_el.find_elements("xpath", ".//a"):
            href = (a.get_attribute("href") or "").lower()
            t = (a.text or "").strip()
            # Facebook post time links point at the permalink and carry a short label
            if t and (t[:1].isdigit() or t[:1] in "bdhjmtayw" or "/posts/" in href):
                parsed = parse_relative_date(t)
                if parsed:
                    candidates.append(parsed)
    except Exception:
        pass
    if not candidates and fallback_text:
        parsed = parse_relative_date(fallback_text)
        if parsed:
            candidates.append(parsed)
    return candidates[0] if candidates else None


class FacebookCollector(BaseCollector):
    data_source = "facebook"

    def __init__(self, config: Dict, cookies_file: Optional[str] = None, headless: bool = True):
        super().__init__(config)
        self.selectors = _load_selectors()
        self.cookies_file = cookies_file or os.environ.get("FACEBOOK_COOKIES_FILE", "") or default_cookies_path()
        self.profile_dir = os.environ.get("FACEBOOK_PROFILE_DIR", "") or default_profile_dir()
        self.headless = headless
        self.driver = None
        self._authorized = False
        self._session_died = False
        self.noise_dropped = 0
        self.noise_reasons = Counter()
        self.date_skipped = 0
        self._community_deadline = None

    def _set_community_deadline(self) -> float:
        """Return the wall-time deadline for the current community.

        Guards against one huge/hung group eating the whole session. Shared by the
        feed scroll loop and the comment/reply crawler so a busy post cannot stall
        the run indefinitely.
        """
        seconds = int(self.config.get("max_seconds_per_community", 1500))
        self._community_deadline = time.time() + seconds
        return self._community_deadline

    def _deadline_passed(self) -> bool:
        return bool(self._community_deadline and time.time() >= self._community_deadline)

    def _apply_noise_filter(self, text: str) -> bool:
        """Return True when the text should be dropped as noise (and count it)."""
        if not (self.config.get("noise_filter", {}).get("enabled", True)):
            return False
        is_noise, reasons = scan_noise(text)
        if is_noise:
            self.noise_dropped += 1
            for r in set(reasons):
                self.noise_reasons[r] += 1
            log.debug("noise dropped [%s]: %s", ",".join(reasons), text[:120])
        return is_noise

    def _kill_stale_chrome(self) -> None:
        """Release the shared Chrome profile before starting a new driver.

        A zombie chrome.exe still holding this project's user-data-dir makes any
        fresh Chrome instance crash at startup with
        'DevToolsActivePort file doesn't exist' (Chrome forwards the launch to the
        running instance and exits). Kill only processes referencing OUR profile.
        """
        if os.name != "nt":
            return
        profile = os.path.normcase(os.path.abspath(self.profile_dir))
        if not os.path.isdir(profile):
            return
        os.environ.setdefault("ADA_CHROME_PROFILE", profile)
        script = (
            "$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
            "-ErrorAction SilentlyContinue;"
            "$prof = $env:ADA_CHROME_PROFILE;"
            "$p | Where-Object { $_.CommandLine -and "
            "$_.CommandLine.IndexOf($prof, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };"
            "Start-Sleep -Milliseconds 800"
        )
        try:
            import subprocess
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, timeout=40)
        except Exception as e:
            log.debug("stale chrome cleanup skipped: %s", e)

    def _init_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-component-update")
        opts.add_argument("--disable-sync")
        opts.add_argument("--mute-audio")
        opts.add_argument("--no-first-run")
        opts.add_argument("--disable-crash-reporter")
        opts.add_argument("--disable-session-crashed-bubble")
        opts.add_argument("--disable-features=CalculateNativeWinOcclusion")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.page_load_strategy = "eager"
        if os.path.isdir(self.profile_dir):
            opts.add_argument(f"--user-data-dir={self.profile_dir}")
            log.info("Reusing authenticated Chrome profile at %s", self.profile_dir)
            self._kill_stale_chrome()
        last_err = None
        for attempt in range(1, 4):
            try:
                self.driver = webdriver.Chrome(options=opts)
                self.driver.set_page_load_timeout(int(self.config.get("page_load_timeout_seconds", 90)))
                log.info("Chrome driver initialised (headless=%s) [attempt %s]", self.headless, attempt)
                return
            except Exception as e:
                last_err = e
                log.warning("Chrome driver start failed (attempt %s): %s", attempt, str(e)[:200])
                try:
                    if self.driver:
                        self.driver.quit()
                except Exception:
                    pass
                self.driver = None
                self._kill_stale_chrome()
                time.sleep(3 * attempt)
        raise last_err if last_err else RuntimeError("Chrome driver start failed repeatedly")

    def _assert_session(self) -> None:
        """Ensure a live, authorized WebDriver session, recycling it when needed.

        Facebook sometimes recycles/heavy tabs die mid-scrape; recreate rather than crash.
        """
        if session_alive(self.driver) and self._authorized:
            return
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = None
        self._authorized = False
        self._init_driver()
        self.check_access()

    def check_access(self) -> None:
        if self._authorized and session_alive(self.driver):
            return
        if not self.driver:
            self._init_driver()
        if not self.driver:
            raise ParserError("Unable to initialise browser driver")

        from selenium.common.exceptions import WebDriverException

        try:
            self.driver.get("https://www.facebook.com")
            time.sleep(3)
            if self.cookies_file and os.path.exists(self.cookies_file):
                with open(self.cookies_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                for c in cookies:
                    d = {"name": c.get("name"), "value": c.get("value"),
                         "domain": c.get("domain"), "path": c.get("path", "/")}
                    if c.get("expirationDate"):
                        d["expiry"] = int(c["expirationDate"])
                    try:
                        self.driver.add_cookie(d)
                    except Exception as e:
                        log.warning("skip cookie %s: %s", c.get("name"), e)
                self.driver.refresh()
                time.sleep(3)

            url = (self.driver.current_url or "").lower()
            markers = self.selectors.get("login_required_markers", [])
            if page_blocked(self.driver) or any(m in url for m in markers):
                saved = save_debug_page(self.driver, "login_wall")
                log.error(
                    "Facebook shows a login wall / checkpoint for this automated session. "
                    "No bypass was attempted. Debug artifacts saved to: %s", saved
                )
                raise AuthenticationError(
                    "Facebook login wall / checkpoint detected. No bypass attempted. "
                    "Please authenticate ONCE with your own account, then retry.\n"
                    "  >>> python -m src.main --mode login\n"
                    f"     (or place an authorized cookies file at: {self.cookies_file})"
                )
            log.info("Facebook session appears authorized (no login wall).")
            self._authorized = True
        except AuthenticationError:
            raise
        except WebDriverException as e:
            raise TemporaryNetworkError(f"Failed to load facebook.com: {e}")

    def iter_posts(self, community: Dict) -> Iterable[Dict]:
        from selenium.webdriver.common.by import By

        self._assert_session()
        if not self.driver:
            return

        community_url = (community.get("url") or "").strip()
        if not community_url:
            log.warning("No community URL configured for %s. Skipping.", community.get("community_name"))
            raise PageUnavailableError(f"No community URL for {community.get('community_name')}")

        max_posts = int(self.config.get("max_posts", 50))
        scroll_max = int(self.config.get("scroll_max_attempts", 40))
        pause = float(self.config.get("scroll_pause_seconds", 3))
        history_since = str(self.config.get("history_since") or "").strip()
        history_dt = None
        if history_since:
            try:
                history_dt = datetime.fromisoformat(history_since).date()
            except ValueError:
                log.warning("Ignoring invalid collection.history_since '%s'", history_since)

        self.driver.get(community_url)
        self.driver.implicitly_wait(pause)
        time.sleep(pause + 2)

        deadline = self._set_community_deadline()
        seen_texts = set()
        collected = 0
        stale = 0
        prev_count = 0
        scroll_iters = 0

        while (collected < max_posts and stale < 6 and scroll_iters < scroll_max
               and time.time() < deadline):
            scroll_iters += 1
            alt_mode = False
            try:
                article_els = self.driver.find_elements(
                    By.CSS_SELECTOR, ", ".join(self.selectors["post_containers"]))
                article_texts = [_safe_text(c) for c in article_els]
            except Exception as e:
                msg = str(e).lower()
                if any(k in msg for k in ("session id", "browser has closed", "disconnected", "devtools")):
                    self._session_died = True
                    log.warning("Facebook browsing session died mid-scrape: %s", msg[:120])
                else:
                    log.warning("post container lookup error: %s", e)
                article_els, article_texts = [], []

            min_len = int(self.config.get("min_text_length", 15))
            valid_pairs = [
                (c, t) for c, t in zip(article_els, article_texts)
                if len(t) >= min_len and not _is_noise_container(t)
            ]

            containers = [c for c, _ in valid_pairs]
            texts = [t for _, t in valid_pairs]
            if not containers:
                # Group feeds render posts in dir=auto blocks rather than
                # role=article containers; fall back when articles carry no text.
                try:
                    containers = self.driver.find_elements(
                        By.CSS_SELECTOR, ", ".join(self.selectors["post_containers_alt"]))
                    texts = [_safe_text(c) for c in containers]
                    alt_mode = True
                    min_len = max(min_len, int(self.config.get("min_post_text_length", 40)))
                except Exception:
                    containers, texts = [], []

            fresh = 0
            for c, text in zip(containers, texts):
                if len(text) < min_len:
                    continue
                if _is_noise_container(text):
                    continue
                if self._apply_noise_filter(text):
                    continue
                if text[:250] in seen_texts:
                    continue
                seen_texts.add(text[:250])
                post_id = _extract_post_id(c) or f"post_{len(seen_texts)}"
                post_date = _extract_post_date(c, text)
                if history_dt is not None and post_date:
                    try:
                        if datetime.fromisoformat(post_date).date() < history_dt:
                            self.date_skipped += 1
                            continue
                    except ValueError:
                        pass
                yield {
                    "vehicle": community.get("vehicle", "unknown"),
                    "community": community.get("community_name", "unknown"),
                    "community_url": community_url,
                    "post_id": post_id,
                    "text": text,
                    "url": _extract_permalink(c, self.driver, community_url),
                    "date": post_date,
                }
                collected += 1
                fresh += 1

            if collected == prev_count:
                stale += 1
            else:
                stale = 0
            prev_count = collected

            if collected >= max_posts:
                break
            try:
                self.driver.execute_script("window.scrollBy(0, 1000)")
            except Exception:
                pass
            time.sleep(pause)

    def iter_comments(self, post: Dict) -> Iterable[Dict]:
        yield from self._iter_threaded_content(post, mode="comment")

    def iter_replies(self, comment: Dict) -> Iterable[Dict]:
        max_replies = int(self.config.get("max_replies_per_comment", 0))
        if max_replies <= 0:
            return
        yield from self._iter_threaded_content(comment, mode="reply")

    def _iter_threaded_content(self, item: Dict, mode: str) -> Iterable[Dict]:
        self._assert_session()
        if not self.driver:
            return
        from selenium.webdriver.common.by import By

        url = (item.get("url") or "").strip()
        if not url:
            return
        max_items = int(self.config.get(
                "max_comments_per_post" if mode == "comment" else "max_replies_per_comment", 40))
        min_len = int(self.config.get("min_text_length", 5))
        deadline = self._set_community_deadline() if not self._community_deadline else self._community_deadline

        loaded = False
        for attempt in range(2):
            try:
                self.driver.get(url)
                time.sleep(2)
                loaded = True
                break
            except Exception as e:
                log.warning("navigating to %s failed (attempt %s): %s", url, attempt + 1, e)
                if not session_alive(self.driver):
                    self._assert_session()
                time.sleep(2)
        if not loaded:
            return

        seen = set()
        count = 0
        # Comments/replies inherit the post date when their own is not extractable.
        parent_date = item.get("date")

        for _ in range(int(self.config.get("scroll_max_attempts", 20))):
            if time.time() >= deadline:
                log.warning("Community deadline reached during %s crawl (%s).",
                            mode, item.get("post_id", "?"))
                break
            self._expand_comment_text()
            try:
                els = self.driver.find_elements(
                    By.CSS_SELECTOR, ", ".join(self.selectors["comment_text"]))
            except Exception:
                els = []
            for el in els:
                text = _safe_text(el)
                if len(text) < int(self.config.get("min_text_length", 5)):
                    continue
                if self._apply_noise_filter(text):
                    continue
                key = (text[:200], mode)
                if key in seen:
                    continue
                seen.add(key)
                cid = f"{item.get('post_id', 'p')}_{mode}_{len(seen)}"
                yield {
                    "vehicle": item.get("vehicle", "unknown"),
                    "community": item.get("community", "unknown"),
                    "community_url": item.get("community_url", ""),
                    "post_id": item.get("post_id", ""),
                    "comment_id": cid if mode == "comment" else item.get("comment_id"),
                    "parent_id": item.get("post_id") if mode == "comment" else item.get("comment_id"),
                    "source_type": mode,
                    "text": text,
                    "url": url,
                    "date": parent_date,
                }
                count += 1
            if count >= max_items:
                break
            try:
                self.driver.execute_script("window.scrollBy(0, 1000)")
                time.sleep(1.5)
            except Exception:
                break

    def _expand_comment_text(self, max_clicks: int = 30) -> None:
        """Click Facebook's 'Lihat selengkapnya' / 'See more' comment expanders.

        Without this, scraped comments are truncated mid-sentence and lose the
        ADAS detail the research depends on.
        """
        if not self.driver:
            return
        from selenium.webdriver.common.by import By
        for _ in range(max_clicks):
            try:
                expanders = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(),'Lihat selengkapnya') or "
                    "contains(text(),'See more') or "
                    "contains(text(),'Lainnya')]",
                )
            except Exception:
                return
            clicked_any = False
            for el in expanders:
                try:
                    if el.is_displayed():
                        el.click()
                        clicked_any = True
                except Exception:
                    continue
            if not clicked_any:
                return
            time.sleep(0.4)

    def close(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self._kill_stale_chrome()


def _extract_post_id(el) -> Optional[str]:
    """Best-effort stable Facebook post id from a feed container.

    Newer group feeds link to /groups/<gid>/permalink/<pid>/ or carry
    story.php?story_fbid=<pid>; older feeds use /groups/<gid>/posts/<pid>/.
    Returning a real id keeps the processed-posts checkpoint working across runs;
    post_N fallbacks break that and cause repeat rescrapes.
    """
    try:
        hrefs = el.find_elements("xpath", ".//a[@href]")
        for h in hrefs:
            href = h.get_attribute("href") or ""
            if "/posts/" in href:
                return href.split("/posts/")[-1].split("/")[0]
            if "/permalink/" in href:
                return href.split("/permalink/")[-1].split("/")[0]
        for h in hrefs:
            href = h.get_attribute("href") or ""
            if "story.php" in href or "story_fbid=" in href:
                m = re.search(r"story_fbid=(\d+)", href)
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


def _extract_permalink(el, driver=None, fallback: str = "") -> str:
    """Best-effort canonical URL of the post inside a feed container.

    Facebook post links look like /groups/xxx/posts/yyy, story.php?story_fbid=...,
    or permalink.php. Falling back to story_url keeps thread crawling working when
    the platform obfuscates links.
    """
    try:
        base = (driver.current_url if driver else None) or "https://www.facebook.com"
        hrefs = el.find_elements("xpath", ".//a[@href]")
        for h in hrefs:
            href = (h.get_attribute("href") or "").strip()
            if not href:
                continue
            if "/posts/" in href or "story.php" in href or "permalink.php" in href:
                return urljoin(base, href)
    except Exception:
        pass
    if fallback:
        story = f"{fallback.rstrip('/')}/posts/"
        return story if "/posts/" in fallback else fallback
    return fallback