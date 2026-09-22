"""First-party, authorized Facebook session management.

Flow is intentionally MANUAL and compliance-safe:

1.  A visible (non-headless) Chrome window opens at https://www.facebook.com
2.  The USER logs in themselves (types credentials, solves any CAPTCHA by hand).
    This code NEVER sends keys to login/password fields and never bypasses anything.
3.  After login the USER presses Enter in the terminal.
4.  The script verifies the session (c_user/xs cookies), then:
      - persists the Chrome profile under data/browser_profiles/facebook so later
        headless runs can reuse the authenticated session;
      - dumps first-party cookies to a cookies JSON that can also be injected.

If the user declines or the platform blocks it, the script prints guidance and
exits without any evasion.
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from src.config_loader import ensure_dirs

log = logging.getLogger(__name__)


def default_profile_dir() -> str:
    env = os.environ.get("FACEBOOK_PROFILE_DIR", "")
    if env:
        return env
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data")
    return os.path.abspath(os.path.join(data_dir, "browser_profiles", "facebook"))


def default_cookies_path() -> str:
    env = os.environ.get("FACEBOOK_COOKIES_FILE", "")
    if env:
        return env
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(os.path.join(base, "..", "data", "cookies_facebook.json"))


def is_logged_in(driver) -> bool:
    """Detect whether the loaded facebook.com session is authenticated.

    Deterministic check: presence of the c_user / xs first-party cookies.
    """
    try:
        names = {c.get("name") for c in driver.get_cookies()}
    except Exception:
        return False
    return bool({"c_user", "xs"} & names)


def session_alive(driver) -> bool:
    """Cheap probe whether the WebDriver session is still usable.

    A dead/recycled Chrome tab raises InvalidSessionIdException on any command.
    """
    if driver is None:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def page_blocked(driver) -> bool:
    """Return True when the page shows a login wall or checkpoint."""
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        url = ""
    if "login" in url or "checkpoint" in url or "confirm" in url:
        return True
    return not is_logged_in(driver)


def save_debug_page(driver, tag: str = "blocked") -> str:
    """Persist a screenshot + DOM snippet for the researcher to review manually."""
    ensure_dirs()
    debug_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "logs", "debug")
    os.makedirs(debug_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    urls = {"html": None, "png": None, "txt": None}
    html_path = os.path.join(debug_dir, f"fb_{tag}_{stamp}.html")
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source or "")
        urls["html"] = html_path
    except Exception as e:
        log.warning("debug html dump failed: %s", e)
    try:
        img_path = os.path.join(debug_dir, f"fb_{tag}_{stamp}.png")
        driver.save_screenshot(img_path)
        urls["png"] = img_path
    except Exception as e:
        log.warning("debug screenshot failed: %s", e)
    try:
        url_text = driver.current_url
        with open(os.path.join(debug_dir, f"fb_{tag}_{stamp}.txt"), "w", encoding="utf-8") as f:
            f.write(url_text or "")
        urls["txt"] = os.path.join(debug_dir, f"fb_{tag}_{stamp}.txt")
    except Exception:
        pass
    return html_path or ""


def interactive_login(profile_dir: Optional[str] = None,
                      cookies_path: Optional[str] = None) -> Dict:
    """Open a visible browser window and let the user log in manually.

    Returns dict with the persisted profile path and cookies path. Raises
    RuntimeError if the user does not finish logging in.
    """
    profile_dir = profile_dir or default_profile_dir()
    cookies_path = cookies_path or default_cookies_path()
    os.makedirs(profile_dir, exist_ok=True)

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.page_load_strategy = "eager"
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(120)
    log.info("Opening facebook.com in a visible browser. Please log in MANUALLY.")
    print("=" * 70)
    print("STEP 1: A Chrome window should open at facebook.com")
    print("STEP 2: Log in to your OWN account manually in that window.")
    print("        (Type your credentials yourself and solve any CAPTCHA yourself.)")
    print("STEP 3: When you see your Facebook home page, return here and press Enter.")
    print("=" * 70)

    try:
        driver.get("https://www.facebook.com")
        time.sleep(2)
        input(">>> Press Enter AFTER you have logged in manually: ")

        if page_blocked(driver):
            save_debug_page(driver, "login_pending")
            print("[WARN] The browser still appears to be on a login/checkpoint page.")
            again = input(">>> Log in properly, then press Enter again (or type 'quit'): ")
            if again.strip().lower() in ("quit", "q", "exit"):
                driver.quit()
                raise RuntimeError("User cancelled login flow.")
            if page_blocked(driver):
                save_debug_page(driver, "login_pending_final")
                driver.quit()
                raise RuntimeError(
                    "Session still not authenticated. Screenshot saved under logs/debug/.")

        # verified
        cookies = driver.get_cookies()
        os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        log.info("Cookies saved to %s", cookies_path)
        print("Session OK.")
        print(f"  profile dir : {profile_dir}")
        print(f"  cookies file: {cookies_path}")
        print("Now run: python -m src.main --mode scrape --vehicle \"Jaecoo J5\" --data-source facebook")
        return {"profile_dir": profile_dir, "cookies_path": cookies_path}
    finally:
        try:
            driver.quit()
        except Exception:
            pass