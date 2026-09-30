"""Preview or force the company claims migration (free-text claim -> CLAIM_TYPES).

The migration itself lives in ``companyresearch.claim_migration`` and now runs
automatically at app startup (api/main.py lifespan) whenever legacy claims
exist. This script is for previewing (dry run) or forcing it manually.

Usage::

    python scripts/migrate_company_claims.py            # dry run, writes nothing
    python scripts/migrate_company_claims.py --apply     # rewrites for real
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companyresearch.claim_migration import _load_raw, apply_migration, build_report


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the migration (dry run by default), print JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = parser.parse_args(argv)
    if args.apply:
        report = apply_migration()
        heading = "applied changes"
    else:
        report = build_report(_load_raw())
        heading = "dry run (nothing written)"
    print(f"=== company claims migration: {heading} ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
