"""Local-only doctor state seeder for end-to-end shake-out.

Quickly flips a single doctor row (and its journey/consent/onboarding
rows) between the three meaningful entry states so you can drive the
journey engines against a real WhatsApp number without hand-editing
DBeaver after every test.

Usage examples (from repo root, `.env` loaded):

    # Wipe everything for the phone — next inbound is Case A (fresh).
    python scripts/seed_state.py 9867401411 fresh

    # Doctor row with a partial profile, no journey row — next inbound
    # hits Case D (partial-confirm Yes/No template).
    python scripts/seed_state.py 9867401411 partial

    # Doctor with profile complete + not onboarded — next inbound hits
    # Case C (consent template send).
    python scripts/seed_state.py 9867401411 complete-not-onboarded

The script is destructive within the rows it touches: it deletes the
matching `journey_state`, `journey_state_history`, `consent`,
`consent_history`, and `whatsapp_onboarding_status` rows for the
doctor before re-seeding. The `doctor` row itself is upserted.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete

from wabot.data.db import dispose_engine, session_scope
from wabot.data.models.consent import Consent, ConsentHistory
from wabot.data.models.doctor import Doctor
from wabot.data.models.journey import JourneyState, JourneyStateHistory
from wabot.data.models.onboarding import WhatsappOnboardingStatus
from wabot.data.repositories import DoctorRepository
from wabot.infra.logging import configure_logging, get_logger

if TYPE_CHECKING:
    import uuid

logger = get_logger(__name__)


STATES: Final[tuple[str, ...]] = ("fresh", "partial", "complete-not-onboarded")


async def _clear_journey_and_consent(session, doctor_id: uuid.UUID) -> None:
    await session.execute(
        delete(JourneyStateHistory).where(JourneyStateHistory.doctor_id == doctor_id)
    )
    await session.execute(delete(JourneyState).where(JourneyState.doctor_id == doctor_id))
    await session.execute(delete(ConsentHistory).where(ConsentHistory.doctor_id == doctor_id))
    await session.execute(delete(Consent).where(Consent.doctor_id == doctor_id))
    await session.execute(
        delete(WhatsappOnboardingStatus).where(WhatsappOnboardingStatus.doctor_id == doctor_id)
    )


async def _seed_fresh(session, phone: str) -> uuid.UUID | None:
    repo = DoctorRepository(session)
    doctor = await repo.get_by_phone(phone)
    if doctor is None:
        return None
    await _clear_journey_and_consent(session, doctor.id)
    await session.execute(delete(Doctor).where(Doctor.id == doctor.id))
    return None


async def _seed_partial(session, phone: str) -> uuid.UUID:
    repo = DoctorRepository(session)
    doctor = await repo.upsert_profile(
        full_phone_number=phone,
        first_name="Test",
        last_name=None,
        speciality="Cardiology",
        email=None,
        address=None,
        city=None,
        state=None,
        pincode=None,
        is_profile_complete=False,
    )
    await _clear_journey_and_consent(session, doctor.id)
    # Stamp registration_completed_at None — repo only sets it on full
    # completion, so this is already correct after upsert.
    doctor.registration_completed_at = None
    await session.flush()
    return doctor.id


async def _seed_complete_not_onboarded(session, phone: str) -> uuid.UUID:
    repo = DoctorRepository(session)
    doctor = await repo.upsert_profile(
        full_phone_number=phone,
        first_name="Test",
        last_name="Doctor",
        speciality="Cardiology",
        email="test.doctor@example.com",
        address="221B Baker Street",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        is_profile_complete=True,
    )
    await _clear_journey_and_consent(session, doctor.id)
    return doctor.id


async def _run(phone: str, state: str) -> int:
    try:
        async with session_scope() as session:
            if state == "fresh":
                await _seed_fresh(session, phone)
                logger.info("wabot.seed_state.fresh", phone=phone)
            elif state == "partial":
                doctor_id = await _seed_partial(session, phone)
                logger.info(
                    "wabot.seed_state.partial",
                    phone=phone,
                    doctor_id=str(doctor_id),
                )
            elif state == "complete-not-onboarded":
                doctor_id = await _seed_complete_not_onboarded(session, phone)
                logger.info(
                    "wabot.seed_state.complete_not_onboarded",
                    phone=phone,
                    doctor_id=str(doctor_id),
                )
            else:  # pragma: no cover - argparse guards this
                return 2
    finally:
        await dispose_engine()
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a doctor into a specific state.")
    parser.add_argument("phone", help="full_phone_number, digits only (e.g. 919867401411)")
    parser.add_argument("state", choices=STATES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    configure_logging()
    return asyncio.run(_run(args.phone, args.state))


if __name__ == "__main__":
    raise SystemExit(main())
