"""Run preflight, then start the loopback-only STRIVE presentation server."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--research", action="store_true")
    args = parser.parse_args()
    if not args.research:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/presentation_check.py"), "--port", str(args.port)])
        if result.returncode:
            raise SystemExit("Presentation preflight failed; server was not started")
        os.environ["STRIVE_CONFIG"] = str(ROOT / "config/presentation.json")
    else:
        os.environ["STRIVE_CONFIG"] = str(ROOT / "config/research.json")
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        def open_when_ready():
            for _ in range(80):
                try:
                    urllib.request.urlopen(url + "/health", timeout=.5).close()
                    webbrowser.open(url); return
                except Exception:
                    time.sleep(.25)
        threading.Thread(target=open_when_ready, daemon=True).start()
    os.chdir(ROOT)
    os.environ["HF_HUB_OFFLINE"] = "1"; os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import uvicorn
    print(f"Runtime mode: {'RESEARCH NEURAL' if args.research else 'DEMO DSP'}")
    print(f"STRIVE dashboard: {url}")
    uvicorn.run("strive.api:app", host="127.0.0.1", port=args.port, proxy_headers=False,
                ws_max_size=22 * 1024 * 1024, ws_max_queue=8, limit_concurrency=24, timeout_keep_alive=10)


if __name__ == "__main__":
    main()
