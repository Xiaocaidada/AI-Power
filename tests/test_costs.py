import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ModelCatalog, UsageEvent


async def _add_catalog(input_price: float, output_price: float) -> None:
    async with SessionLocal() as session:
        session.add(
            ModelCatalog(
                provider_id="fake",
                model_id="fake-model",
                display_name="Fake",
                input_price=input_price,
                output_price=output_price,
            )
        )
        await session.commit()


async def _send_message(client, headers) -> None:
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "cost please"},
        headers=headers,
    )
    assert response.status_code == 200


async def _cost(client, headers, group_by: str = "day"):
    return await client.get(f"/usage/cost?group_by={group_by}", headers=headers)


async def _events() -> list[UsageEvent]:
    async with SessionLocal() as session:
        return list((await session.execute(select(UsageEvent))).scalars())


async def test_cost_uses_price_snapshot(client, api, registry, fake_provider):
    await _add_catalog(input_price=1.0, output_price=2.0)
    headers = await api.headers("cost-basic@example.com")

    await _send_message(client, headers)

    response = await _cost(client, headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_cost"] == pytest.approx(5e-06)
    assert body["unpriced_requests"] == 0
    assert len(body["buckets"]) == 1
    assert body["buckets"][0]["cost"] == pytest.approx(5e-06)
    assert body["buckets"][0]["requests"] == 1

    grouped = (await _cost(client, headers, group_by="model")).json()
    assert grouped["buckets"][0]["key"] == "fake-model"
    assert grouped["total_cost"] == pytest.approx(5e-06)

    events = await _events()
    assert events[0].input_price == 1.0
    assert events[0].output_price == 2.0
    assert events[0].cost == pytest.approx(5e-06)
    assert events[0].unpriced is False


async def test_price_changes_do_not_rewrite_history(client, api, registry, fake_provider):
    await _add_catalog(input_price=1.0, output_price=2.0)
    headers = await api.headers("cost-history@example.com")
    await _send_message(client, headers)

    async with SessionLocal() as session:
        entry = (await session.execute(select(ModelCatalog))).scalars().one()
        entry.input_price = 100.0
        entry.output_price = 200.0
        await session.commit()

    first = (await _cost(client, headers)).json()
    assert first["total_cost"] == pytest.approx(5e-06)

    await _send_message(client, headers)
    second = (await _cost(client, headers)).json()

    assert second["total_cost"] == pytest.approx(0.000505)
    events = await _events()
    assert events[0].cost == pytest.approx(5e-06)
    assert events[1].input_price == 100.0


async def test_unpriced_model_counts_zero_and_is_flagged(client, api, registry, fake_provider):
    headers = await api.headers("cost-unpriced@example.com")

    await _send_message(client, headers)

    body = (await _cost(client, headers)).json()
    assert body["total_cost"] == 0
    assert body["unpriced_requests"] == 1
    assert body["buckets"][0]["unpriced_requests"] == 1
    events = await _events()
    assert events[0].unpriced is True
    assert events[0].cost == 0


async def test_cost_is_workspace_scoped(client, api, registry, fake_provider):
    await _add_catalog(input_price=1.0, output_price=2.0)
    alice = await api.headers("cost-alice@example.com")
    bob = await api.headers("cost-bob@example.com")
    await _send_message(client, alice)
    await _send_message(client, bob)

    alice_cost = (await _cost(client, alice)).json()

    assert alice_cost["total_cost"] == pytest.approx(5e-06)
    assert alice_cost["buckets"][0]["requests"] == 1


async def test_null_usage_is_zero_cost_not_unpriced(client, api, registry, fake_provider):
    from app.providers.base import ChatChunk

    fake_provider.chunks = [ChatChunk(delta="Hi"), ChatChunk(finish_reason="stop")]
    await _add_catalog(input_price=1.0, output_price=2.0)
    headers = await api.headers("cost-null@example.com")

    await _send_message(client, headers)

    body = (await _cost(client, headers)).json()
    assert body["total_cost"] == 0
    assert body["unpriced_requests"] == 0
    events = await _events()
    assert events[0].cost == 0
    assert events[0].unpriced is False
