"""One-shot doctor master-data import.

Reads a CSV with the columns shown in `EXPECTED_COLUMNS` and upserts each
row into `wabot.doctor`. Records flagged ``is_profile_complete=true`` set
``registration_completed_at`` to ``clock_timestamp()`` server-side.

Usage (from repo root, with `.env` loaded by the app config):
    python scripts/seed_doctors.py path/to/doctors.csv [--dry-run]

The script is intentionally simple: idempotent on `full_phone_number`,
no fancy chunking. It is meant for the **one-time** master-data load
described in §A4 of the implementation plan.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import Any

from wabot.data.db import dispose_engine, session_scope
from wabot.data.repositories import DoctorRepository
from wabot.infra.logging import configure_logging, get_logger

EXPECTED_COLUMNS = (
    "full_phone_number",
    "first_name",
    "last_name",
    "speciality",
    "email",
    "address",
    "city",
    "state",
    "pincode",
    "is_profile_complete",
)

logger = get_logger(__name__)


def _coerce_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "t", "yes", "y"}


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 10:
        msg = f"Phone number too short after normalization: {value!r}"
        raise ValueError(msg)
    return digits


def _row_to_kwargs(row: dict[str, str]) -> dict[str, Any]:
    return {
        "full_phone_number": _normalize_phone(row["full_phone_number"]),
        "first_name": (row.get("first_name") or "").strip() or None,
        "last_name": (row.get("last_name") or "").strip() or None,
        "speciality": (row.get("speciality") or "").strip() or None,
        "email": (row.get("email") or "").strip() or None,
        "address": (row.get("address") or "").strip() or None,
        "city": (row.get("city") or "").strip() or None,
        "state": (row.get("state") or "").strip() or None,
        "pincode": (row.get("pincode") or "").strip() or None,
        "is_profile_complete": _coerce_bool(row.get("is_profile_complete")),
    }


async def import_csv(path: Path, *, dry_run: bool) -> tuple[int, int]:
    inserted = 0
    updated = 0

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [col for col in EXPECTED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            msg = f"CSV is missing required columns: {missing}"
            raise ValueError(msg)
        rows = [_row_to_kwargs(row) for row in reader]

    if dry_run:
        for r in rows:
            logger.info("seed.doctor.preview", **r)
        return len(rows), 0

    async with session_scope() as session:
        repo = DoctorRepository(session)
        for r in rows:
            existing = await repo.get_by_phone(r["full_phone_number"])
            await repo.upsert_profile(**r)
            if existing is None:
                inserted += 1
            else:
                updated += 1

    return inserted, updated


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk import doctor master data.")
    parser.add_argument("csv_path", type=Path, help="Path to the CSV file.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to the database.",
    )
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    configure_logging()
    if not args.csv_path.is_file():
        logger.error("seed.csv_missing", path=str(args.csv_path))
        return 2

    try:
        inserted, updated = await import_csv(args.csv_path, dry_run=args.dry_run)
    finally:
        await dispose_engine()

    logger.info(
        "seed.done",
        path=str(args.csv_path),
        inserted=inserted,
        updated=updated,
        dry_run=args.dry_run,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
