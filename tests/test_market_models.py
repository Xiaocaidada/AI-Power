from sqlalchemy import select

from app.db import SessionLocal
from app.models import User


async def _make_admin(email: str) -> None:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.role = "admin"
        await session.commit()


def _payload(slug: str = "demo-chat") -> dict[str, object]:
    return {
        "slug": slug,
        "name": "Demo Chat",
        "provider_id": "fake",
        "provider_name": "Fake",
        "model_id": "fake-model",
        "description": "A demo model for marketplace tests",
        "category": "general",
        "capabilities": ["chat", "stream", "tools"],
        "input_types": ["text"],
        "output_types": ["text"],
        "context_window": 8192,
        "featured": True,
        "is_new": True,
    }


async def test_public_market_models_require_no_login(client, api):
    admin = await api.headers("market-admin@example.com")
    await _make_admin("market-admin@example.com")
    created = await client.post("/admin/market/models", json=_payload(), headers=admin)
    assert created.status_code == 201

    listed = await client.get("/market/models")

    assert listed.status_code == 200
    models = listed.json()
    assert models[0]["slug"] == "demo-chat"
    assert models[0]["available"] is False
    assert models[0]["featured"] is True

    detail = await client.get("/market/models/demo-chat")
    assert detail.status_code == 200
    assert detail.json()["context_window"] == 8192
    assert (await client.get("/market/models/missing")).status_code == 404


async def test_public_market_search_and_filters(client, api):
    admin = await api.headers("market-filter@example.com")
    await _make_admin("market-filter@example.com")
    assert (
        await client.post("/admin/market/models", json=_payload(), headers=admin)
    ).status_code == 201
    second = _payload("coder")
    second.update(
        {
            "name": "Coder",
            "model_id": "coder-model",
            "category": "coding",
            "capabilities": ["chat", "stream"],
            "featured": False,
            "is_new": False,
        }
    )
    assert (
        await client.post("/admin/market/models", json=second, headers=admin)
    ).status_code == 201

    search = await client.get("/market/models?search=coder")
    assert [item["slug"] for item in search.json()] == ["coder"]
    coding = await client.get("/market/models?category=coding")
    assert [item["slug"] for item in coding.json()] == ["coder"]
    tools = await client.get("/market/models?capability=tools")
    assert [item["slug"] for item in tools.json()] == ["demo-chat"]
    newest = await client.get("/market/models?sort=new")
    assert [item["slug"] for item in newest.json()] == ["demo-chat", "coder"]


async def test_market_admin_is_hidden_and_disable_hides_model(client, api):
    plain = await api.headers("market-plain@example.com")
    assert (await client.get("/admin/market/models", headers=plain)).status_code == 404

    admin = await api.headers("market-admin2@example.com")
    await _make_admin("market-admin2@example.com")
    created = await client.post("/admin/market/models", json=_payload(), headers=admin)
    model_id = created.json()["id"]

    disabled = await client.patch(
        f"/admin/market/models/{model_id}", json={"enabled": False}, headers=admin
    )
    assert disabled.status_code == 200
    assert (await client.get("/market/models")).json() == []
    assert (await client.get("/market/models/demo-chat")).status_code == 404
    admin_list = await client.get("/admin/market/models", headers=admin)
    assert len(admin_list.json()) == 1


async def test_duplicate_market_model_is_rejected(client, api):
    admin = await api.headers("market-dup@example.com")
    await _make_admin("market-dup@example.com")
    assert (
        await client.post("/admin/market/models", json=_payload(), headers=admin)
    ).status_code == 201
    duplicate = await client.post("/admin/market/models", json=_payload(), headers=admin)
    assert duplicate.status_code == 409
