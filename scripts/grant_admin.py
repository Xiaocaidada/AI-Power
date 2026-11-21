"""Grant the platform admin role to an existing user.

Usage:
    python scripts/grant_admin.py user@example.com
"""

import asyncio
import sys

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import User


async def grant(email: str) -> bool:
    await init_db()
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email.strip().lower()))
        ).scalar_one_or_none()
        if user is None:
            return False
        user.role = "admin"
        await session.commit()
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/grant_admin.py <email>")
        return 2
    email = sys.argv[1]
    if not asyncio.run(grant(email)):
        print(f"user not found: {email}")
        return 1
    print(f"granted admin: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
