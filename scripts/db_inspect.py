import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    from wabot.infra.config import get_settings

    s = get_settings()
    e = create_async_engine(s.db_dsn, connect_args={"ssl": True})
    queries = [
        ("SELECT * FROM wabot.journey_state", "journey_state"),
        ("SELECT COUNT(*) FROM wabot.conversation_session", "session_count"),
        (
            "SELECT direction, COUNT(*) FROM wabot.conversation_message "
            "GROUP BY direction ORDER BY direction",
            "msg_count",
        ),
        (
            "SELECT kind, template_name, status FROM wabot.outbound_message ORDER BY created_at",
            "outbound_list",
        ),
        (
            "SELECT direction, left(coalesce(text, payload::text), 90) AS body "
            "FROM wabot.conversation_message ORDER BY created_at",
            "messages",
        ),
    ]
    async with e.connect() as c:
        for q, label in queries:
            print(f"--- {label} ---")
            for row in (await c.execute(text(q))).all():
                print(row)


asyncio.run(main())
