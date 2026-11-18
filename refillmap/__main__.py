"""Run the refillmap server: python -m refillmap --port 8099"""

from __future__ import annotations

import argparse

from .server import App, serve


def main() -> None:
    parser = argparse.ArgumentParser(description="refillmap server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--no-live", action="store_true", help="Disable live Overpass fetch")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()
    app = App(data_dir=args.data_dir, cache_dir=args.cache_dir, allow_live=not args.no_live)
    serve(args.host, args.port, app)


if __name__ == "__main__":
    main()