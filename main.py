#!/usr/bin/env python
"""FXCorrMonitor orchestration CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import init_db
from src.ingestion import IngestionError, ingest_excel
from src.utils import DEFAULT_DB_PATH, resolve_path, setup_logging


def cmd_init_db(args: argparse.Namespace) -> int:
    path = resolve_path(args.db)
    init_db(path, replace=args.replace)
    print(f"Initialized DB: {path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    setup_logging(args.verbose)
    try:
        result = ingest_excel(
            file_path=args.file,
            db_path=args.db,
            replace=args.replace,
            verbose=args.verbose,
        )
    except (FileNotFoundError, IngestionError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(
        f"OK inserted={result['inserted_rows']} updated={result['updated_rows']} "
        f"missing_sheets={result['missing_sheets']}"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    app_path = PROJECT_ROOT / "app" / "app.py"
    port = args.port if args.port is not None else 8502
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
    ]
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FXCorrMonitor orchestration")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Create SQLite schema")
    p_init.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_init.add_argument("--replace", action="store_true")
    p_init.set_defaults(func=cmd_init_db)

    p_ing = sub.add_parser("ingest", help="Ingest Infomax Excel")
    p_ing.add_argument("--file", required=True)
    p_ing.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_ing.add_argument("--replace", action="store_true")
    p_ing.add_argument("--verbose", action="store_true")
    p_ing.set_defaults(func=cmd_ingest)

    p_run = sub.add_parser("run", help="Launch Streamlit dashboard")
    p_run.add_argument("--port", type=int, default=8502, help="Server port (default: 8502)")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
