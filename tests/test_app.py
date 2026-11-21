from app.db import init_db
from app.main import app


async def test_init_db_creates_tables():
    await init_db()


async def test_app_lifespan_runs_init_db():
    async with app.router.lifespan_context(app):
        pass
