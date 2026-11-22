from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, User


async def _make_admin(email: str) -> None:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.role = "admin"
        await session.commit()


def _placement(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "banner",
        "title": "Welcome banner",
        "subtitle": "Try the new portal",
        "link_url": "/models",
        "link_label": "Browse models",
    }
    payload.update(overrides)
    return payload


def _announcement(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Platform update",
        "summary": "New features are live",
        "body": "Detailed announcement body.",
        "category": "update",
        "status": "published",
    }
    payload.update(overrides)
    return payload


async def test_home_feed_and_announcements_are_public(client, api):
    admin = await api.headers("content-admin@example.com")
    await _make_admin("content-admin@example.com")

    banner = await client.post(
        "/admin/content/placements", json=_placement(), headers=admin
    )
    assert banner.status_code == 201
    announcement = await client.post(
        "/admin/content/announcements",
        json=_announcement(title="Hello world", pinned=True),
        headers=admin,
    )
    assert announcement.status_code == 201
    announcement_id = announcement.json()["id"]

    home = await client.get("/home")
    assert home.status_code == 200
    feed = home.json()
    assert [item["title"] for item in feed["banners"]] == ["Welcome banner"]
    assert [item["title"] for item in feed["announcements"]] == ["Hello world"]

    listing = await client.get("/announcements")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [announcement_id]

    detail = await client.get(f"/announcements/{announcement_id}")
    assert detail.status_code == 200
    assert detail.json()["body"] == "Detailed announcement body."


async def test_home_content_respects_schedule_and_status(client, api):
    admin = await api.headers("content-window@example.com")
    await _make_admin("content-window@example.com")
    now = datetime.now(UTC)

    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()

    assert (
        await client.post(
            "/admin/content/placements",
            json=_placement(title="Scheduled", starts_at=future),
            headers=admin,
        )
    ).status_code == 201
    assert (
        await client.post(
            "/admin/content/placements",
            json=_placement(title="Expired", ends_at=past),
            headers=admin,
        )
    ).status_code == 201
    assert (
        await client.post(
            "/admin/content/placements",
            json=_placement(title="Disabled", enabled=False),
            headers=admin,
        )
    ).status_code == 201

    draft = await client.post(
        "/admin/content/announcements", json=_announcement(status="draft"), headers=admin
    )
    scheduled = await client.post(
        "/admin/content/announcements",
        json=_announcement(title="Scheduled", published_at=future),
        headers=admin,
    )
    expired = await client.post(
        "/admin/content/announcements",
        json=_announcement(
            title="Expired",
            published_at=(now - timedelta(days=2)).isoformat(),
            expires_at=past,
        ),
        headers=admin,
    )
    assert draft.status_code == scheduled.status_code == expired.status_code == 201

    home = await client.get("/home")
    assert home.json()["banners"] == []
    assert home.json()["announcements"] == []
    assert (await client.get("/announcements")).json() == []
    assert (await client.get(f"/announcements/{draft.json()['id']}")).status_code == 404
    assert (await client.get(f"/announcements/{scheduled.json()['id']}")).status_code == 404
    assert (await client.get(f"/announcements/{expired.json()['id']}")).status_code == 404

    admin_placements = await client.get("/admin/content/placements", headers=admin)
    assert len(admin_placements.json()) == 3
    admin_announcements = await client.get("/admin/content/announcements", headers=admin)
    assert len(admin_announcements.json()) == 3


async def test_notifications_are_per_user_and_mark_read(client, api):
    admin = await api.headers("content-notify-admin@example.com")
    await _make_admin("content-notify-admin@example.com")
    alice = await api.headers("content-alice@example.com")
    bob = await api.headers("content-bob@example.com")

    first = await client.post(
        "/admin/content/announcements", json=_announcement(title="First"), headers=admin
    )
    second = await client.post(
        "/admin/content/announcements", json=_announcement(title="Second"), headers=admin
    )
    assert first.status_code == second.status_code == 201

    alice_feed = await client.get("/notifications", headers=alice)
    assert alice_feed.status_code == 200
    assert alice_feed.json()["unread_count"] == 2
    assert {item["title"] for item in alice_feed.json()["items"]} == {"First", "Second"}

    read = await client.post(
        f"/notifications/{first.json()['id']}/read", headers=alice
    )
    assert read.status_code == 200
    assert read.json()["read_at"] is not None

    alice_after = (await client.get("/notifications", headers=alice)).json()
    assert alice_after["unread_count"] == 1

    bob_feed = (await client.get("/notifications", headers=bob)).json()
    assert bob_feed["unread_count"] == 2

    marked = await client.post("/notifications/read-all", headers=alice)
    assert marked.status_code == 200
    assert marked.json()["marked"] == 1
    assert (await client.get("/notifications", headers=alice)).json()["unread_count"] == 0

    assert (await client.get("/notifications")).status_code == 401
    missing = await client.post(
        "/notifications/00000000-0000-0000-0000-000000000000/read", headers=alice
    )
    assert missing.status_code == 404


async def test_content_admin_surface_is_hidden_and_audited(client, api):
    plain = await api.headers("content-plain@example.com")
    assert (await client.get("/admin/content/announcements", headers=plain)).status_code == 404
    assert (await client.get("/admin/content/placements", headers=plain)).status_code == 404

    admin = await api.headers("content-audit@example.com")
    await _make_admin("content-audit@example.com")
    created = await client.post(
        "/admin/content/announcements", json=_announcement(), headers=admin
    )
    assert created.status_code == 201

    async with SessionLocal() as session:
        actions = (
            await session.execute(
                select(AuditLog.action).where(
                    AuditLog.action == "content.announcement_create"
                )
            )
        ).scalars().all()
    assert actions == ["content.announcement_create"]


async def test_unsafe_links_are_rejected(client, api):
    admin = await api.headers("content-url@example.com")
    await _make_admin("content-url@example.com")

    placement = await client.post(
        "/admin/content/placements",
        json=_placement(link_url="javascript:alert(1)"),
        headers=admin,
    )
    assert placement.status_code == 422

    announcement = await client.post(
        "/admin/content/announcements",
        json=_announcement(cover_url="data:text/html;base64,abc"),
        headers=admin,
    )
    assert announcement.status_code == 422

    protocol_relative = await client.post(
        "/admin/content/placements",
        json=_placement(link_url="//evil.example.com"),
        headers=admin,
    )
    assert protocol_relative.status_code == 422