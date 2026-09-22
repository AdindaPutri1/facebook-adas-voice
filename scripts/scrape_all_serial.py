import os, sys, subprocess, time
from datetime import datetime

os.chdir(r"C:\Users\msi\facebook-adas-voice")
sys.path.insert(0, r"C:\Users\msi\facebook-adas-voice")

from src.config_loader import load_vehicles
from src.collectors.facebook_session import default_profile_dir

CR_NEW_PROC_GRP = 0x00000200
CR_NO_WINDOW = 0x08000000
PROFILE_DIR = default_profile_dir()


def cleanup_chrome() -> None:
    """Kill zombie chrome.exe still holding our shared profile (Windows)."""
    if os.name != "nt":
        return
    os.environ.setdefault("ADA_CHROME_PROFILE", os.path.normcase(os.path.abspath(PROFILE_DIR)))
    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
        "-ErrorAction SilentlyContinue;"
        "$prof = $env:ADA_CHROME_PROFILE;"
        "$p | Where-Object { $_.CommandLine -and "
        "$_.CommandLine.IndexOf($prof, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };"
        "Start-Sleep -Milliseconds 1000"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=40)
    except Exception:
        pass


def build_order() -> list:
    seen = set()
    order = []
    for vkey, v in sorted(load_vehicles().get("vehicles", {}).items(),
                          key=lambda kv: kv[0]):
        canonical = v.get("canonical_name", vkey)
        if canonical in seen:
            continue
        seen.add(canonical)
        order.append((vkey, canonical))
    # Jaecoo community crashes Chrome; run it last so a failure cannot starve others.
    order = [o for o in order if "jaecoo" not in o[0].lower()] \
        + [o for o in order if "jaecoo" in o[0].lower()]
    return order


if __name__ == "__main__":
    only = [a.lower() for a in sys.argv[1:]]
    order = build_order()
    if only:
        order = [o for o in order if any(word in o[0].lower() or word in o[1].lower() for word in only)]
    if not order:
        print("No vehicles matched filter:", sys.argv[1:])
        sys.exit(2)
    print("vehicles for serial scrape:", order, flush=True)

    done = []
    failed = []
    for vkey, canonical in order:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log = os.path.join("logs", f"scrape_{vkey}_{stamp}.log")
        print(f"=== [{datetime.now().strftime('%H:%M:%S')}] scraping {canonical} -> {log}", flush=True)
        cleanup_chrome()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        with open(log, "w", encoding="utf-8") as fh:
            r = subprocess.run(
                [sys.executable, "-m", "src.main", "--mode", "scrape",
                 "--vehicle", canonical, "--data-source", "facebook"],
                cwd=r"C:\Users\msi\facebook-adas-voice",
                env=env, stdout=fh, stderr=subprocess.STDOUT, text=True,
                creationflags=CR_NEW_PROC_GRP | CR_NO_WINDOW)
        print(f"    {canonical} rc={r.returncode}", flush=True)
        cleanup_chrome()
        if r.returncode == 0:
            done.append(canonical)
        else:
            failed.append((canonical, r.returncode))
        # humane pause between vehicles so FB sees human pacing
        time.sleep(25)

    print("=== SERIAL SCRAPE DONE ===", flush=True)
    print("done:", done, flush=True)
    print("failed:", failed, flush=True)