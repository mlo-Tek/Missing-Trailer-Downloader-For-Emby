from __future__ import annotations

import argparse
import json
import os
import sys

from .config import Settings
from .service import MTDE
from .web import create_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="mtde", description="Missing Trailer Downloader for Emby")
    parser.add_argument("--config", default=os.environ.get("MTDE_CONFIG", "/config/config.yml"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan", action="store_true", help="scan and download missing local trailers")
    mode.add_argument("--dry-run", action="store_true", help="scan/search but do not download")
    mode.add_argument("--test", action="store_true", help="test Emby connection")
    args = parser.parse_args()

    try:
        settings = Settings.from_yaml(args.config)
        service = MTDE(settings)
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.test:
        print(json.dumps(service.test_connection(), indent=2, ensure_ascii=False))
        return 0
    if args.scan or args.dry_run:
        results = service.scan(download=not args.dry_run)
        print(json.dumps(service.serialize(results), indent=2, ensure_ascii=False))
        return 0

    app = create_app(service)
    app.run(host="0.0.0.0", port=settings.web_port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
