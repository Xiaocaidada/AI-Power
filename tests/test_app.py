from app.db import init_db
from app.main import app


async def test_init_db_creates_tables():
    await init_db()


async def test_app_lifespan_runs_init_db():
    async with app.router.lifespan_context(app):
        pass


async def test_openapi_documents_stream_and_admin_contract(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "AI Power API"
    tags = {tag["name"] for tag in spec.get("tags", [])}
    assert {"conversations", "prompt-templates", "admin"} <= tags
    operation = spec["paths"]["/conversations/{conversation_id}/messages"]["post"]
    assert {"429", "503"} <= set(operation["responses"])
    upload = spec["paths"]["/knowledge-bases/{kb_id}/documents"]["post"]
    assert {"413", "415", "503"} <= set(upload["responses"])
