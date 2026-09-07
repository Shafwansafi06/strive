"""Start the offline local MVP. No credentials or models are downloaded here."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--research", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("STRIVE_API_TOKEN"):
        raise SystemExit("Set STRIVE_API_TOKEN before binding beyond localhost")
    if args.research:
        os.environ["STRIVE_CONFIG"] = str(ROOT / "config" / "research.json")
        os.environ["STRIVE_MODE"] = "research"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import uvicorn
    print(f"STRIVE dashboard: http://{args.host}:{args.port}")
    uvicorn.run("strive.api:app", host=args.host, port=args.port, proxy_headers=False,
                ws_max_size=90000, ws_max_queue=4, limit_concurrency=24, timeout_keep_alive=10)


if __name__ == "__main__":
    main()
