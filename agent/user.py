import os
from dataclasses import dataclass
from datetime import datetime

from db import pool


@dataclass
class User:
    first_name: str
    last_seen: datetime | None
    positioning: str
    roles_wanted: list
    stacks: list

    @classmethod
    def default(cls) -> "User":
        return cls(
            first_name=os.environ.get("USER_FIRST_NAME", "there"),
            last_seen=None,
            positioning="",
            roles_wanted=[],
            stacks=[],
        )

    @classmethod
    async def load(cls) -> "User":
        db_pool = await pool()
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("select field, value from profile")
            last_seen = await conn.fetchval("select last_visit_at from visits limit 1")
        p = {r["field"]: r["value"] for r in rows}
        user = cls(
            first_name=os.environ.get("USER_FIRST_NAME", "there"),
            last_seen=last_seen,
            positioning=(
                p.get("candidate.positioning", "")
                if isinstance(p.get("candidate.positioning", ""), str)
                else ""
            ),
            roles_wanted=_string_list(p.get("candidate.roles_wanted")),
            stacks=_string_list(p.get("candidate.stacks")),
        )
        return user


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
