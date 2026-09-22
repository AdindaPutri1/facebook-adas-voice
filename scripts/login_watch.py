import json
import logging
import os
import sys
import time

sys.path.insert(0, r"C:\Users\msi\facebook-adas-voice")
os.chdir(r"C:\Users\msi\facebook-adas-voice")

import logging.config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(r"logs\login_watch_app.log", mode="w", encoding="utf-8")],
)
log = logging.getLogger("login_watch")

from src.collectors.facebook_session import (
    default_cookies_path,
    default_profile_dir,
    is_logged_in,
    page_blocked,
    save_debug_page,
)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

profile_dir = default_profile_dir()
cookies_path = default_cookies_path()
os.makedirs(profile_dir, exist_ok=True)

opts = Options()
opts.add_argument(f"--user-data-dir={profile_dir}")
opts.add_argument("--window-size=1280,900")
opts.add_argument("--disable-notifications")
opts.add_argument("--disable-gpu")
opts.add_argument("--no-sandbox")
opts.page_load_strategy = "eager"
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_argument("--remote-debugging-pipe")

log.info("Opening chrome with profile %s", profile_dir)
log.info("chrome appears as WATCHER PID %s", os.getpid())

driver = webdriver.Chrome(options=opts)
driver.set_page_load_timeout(120)
driver.get("https://www.facebook.com")
log.info("Browser ready at facebook.com -- waiting for user to log in (max 20 min).")

deadline = time.time() + 20 * 60
ok = False
last_yell = 0
while time.time() < deadline:
    try:
        url = driver.current_url
        if is_logged_in(driver) and not page_blocked(driver):
            ok = True
            log.info("Session authenticated (c_user/xs cookies present). url=%s", url)
            break
    except Exception as e:
        log.warning("Poll error: %s", e)
        save_debug_page(driver, "login_pending")
    if time.time() - last_yell > 120:
        log.info("Still waiting for manual login... url=%s", driver.current_url)
        last_yell = time.time()
    time.sleep(5)

if ok:
    cookies = driver.get_cookies()
    os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
    with open(cookies_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    log.info("Cookies saved to %s (%d cookies)", cookies_path, len(cookies))
    log.info("LOGIN OK")
else:
    save_debug_page(driver, "login_pending_final")
    log.error("LOGIN FAIL: user did not authenticate in time.")
driver.quit()