#!/usr/bin/env python
"""CLI: ingest Infomax Excel into SQLite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion import IngestionError, ingest_excel
from src.utils import setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Infomax Excel into FXCorrMonitor SQLite DB")
    parser.add_argument("--file", required=True, help="Path to Infomax Excel file")
    parser.add_argument(
        "--db",
        default="data/fx_dashboard.db",
        help="SQLite database path (default: data/fx_dashboard.db)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing DB and recreate before ingest",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        result = ingest_excel(
            file_path=args.file,
            db_path=args.db,
            replace=args.replace,
            verbose=args.verbose,
        )
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except IngestionError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[ERROR] 적재 실패: {exc}", file=sys.stderr)
        return 3

    print("=== Ingestion Summary ===")
    print(f"DB:            {result['db_path']}")
    print(f"Source:        {result['source_file']}")
    print(f"Inserted rows: {result['inserted_rows']}")
    print(f"Updated rows:  {result['updated_rows']}")
    print(f"Total rows:    {result['total_rows']}")
    if result["missing_sheets"]:
        print("Missing sheets:")
        for s in result["missing_sheets"]:
            print(f"  - {s}")
    else:
        print("Missing sheets: (none)")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
        for w in result["warnings"]:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
