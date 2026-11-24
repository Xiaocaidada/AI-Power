from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ExternalCall


async def _create_integration(client, headers, **overrides):
    payload = {
        "kind": "image_generation",
        "name": "Images",
        "credential": "sk-test-secret",
        "model": "gpt-image-1",
        "options": {"size": "1024x1024"},
        **overrides,
    }
    return await client.post("/integrations", json=payload, headers=headers)


async def test_integration_crud_encrypts_credentials_and_isolates(client, api):
    alice = await api.headers("p12-s9-config-alice@example.com")
    bob = await api.headers("p12-s9-config-bob@example.com")

    created = await _create_integration(client, alice)
    assert created.status_code == 201
    body = created.json()
    assert body["credential_hint"] != "sk-test-secret"
    assert "sk-test-secret" not in str(body)
    assert body["is_default"] is True
    assert body["owned"] is True

    listed = await client.get("/integrations?kind=image_generation", headers=alice)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    outsider = await client.get(f"/integrations/{body['id']}", headers=bob)
    assert outsider.status_code == 404
    outsider_patch = await client.patch(
        f"/integrations/{body['id']}", json={"name": "Hijack"}, headers=bob
    )
    assert outsider_patch.status_code == 404

    patched = await client.patch(
        f"/integrations/{body['id']}",
        json={"name": "Renamed", "credential": "sk-new-secret"},
        headers=alice,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    removed = await client.delete(f"/integrations/{body['id']}", headers=alice)
    assert removed.status_code == 204
    assert (await client.get(f"/integrations/{body['id']}", headers=alice)).status_code == 404


async def test_github_integration_requires_pat(client, api):
    headers = await api.headers("p12-s9-github-pat@example.com")
    response = await _create_integration(
        client, headers, kind="github", credential="", provider="github"
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "credential_required"


async def test_image_generation_stores_media_and_logs_call(client, api, monkeypatch):
    headers = await api.headers("p12-s9-image@example.com")
    created = await _create_integration(client, headers)
    config_id = created.json()["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64

    async def fake_generate(config, *, prompt, size, n, quality=None, style=None):
        assert config.id == UUID(config_id)
        return [(png, "image/png", "png")]

    monkeypatch.setattr("app.routers.media.generate_images", fake_generate)
    response = await client.post(
        "/images/generations",
        json={"prompt": "a small test image", "size": "512x512", "n": 1},
        headers=headers,
    )
    assert response.status_code == 201
    asset = response.json()[0]
    assert asset["mime"] == "image/png"
    assert asset["url"] == f"/media/{asset['id']}"

    media = await client.get(asset["url"], headers=headers)
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.content.startswith(b"\x89PNG")

    listed = await client.get("/media", headers=headers)
    assert len(listed.json()) == 1
    calls = await client.get("/integrations/calls?kind=image_generation", headers=headers)
    assert calls.json()[0]["operation"] == "image_generation"
    assert calls.json()[0]["status"] == "completed"

    async with SessionLocal() as session:
        persisted = (
            await session.execute(
                select(ExternalCall).where(ExternalCall.operation == "image_generation")
            )
        ).scalar_one()
        assert persisted.units == 1

    removed = await client.delete(f"/media/{asset['id']}", headers=headers)
    assert removed.status_code == 204
    assert (await client.get(f"/media/{asset['id']}", headers=headers)).status_code == 404


async def test_media_retention_cleanup(client, api, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from app.config import get_settings
    from app.services.maintenance import cleanup_media_assets

    headers = await api.headers("p12-s9-media-retention@example.com")
    await _create_integration(client, headers)
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 32

    async def fake_generate(config, *, prompt, size, n, quality=None, style=None):
        return [(png, "image/png", "png")]

    monkeypatch.setattr("app.routers.media.generate_images", fake_generate)
    response = await client.post(
        "/images/generations", json={"prompt": "expire me"}, headers=headers
    )
    assert response.status_code == 201
    asset_id = response.json()[0]["id"]

    async with SessionLocal() as session:
        removed = await cleanup_media_assets(
            session,
            Path(get_settings().upload_dir),
            now=datetime.now(UTC) + timedelta(days=40),
        )
    assert removed == 1
    assert (await client.get(f"/media/{asset_id}", headers=headers)).status_code == 404


async def test_image_requires_configured_integration(client, api):
    headers = await api.headers("p12-s9-image-missing@example.com")
    response = await client.post(
        "/images/generations",
        json={"prompt": "no integration configured"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "integration_not_configured"


async def test_image_edit_and_variation_endpoints(client, api, monkeypatch):
    headers = await api.headers("p12-s9-image-edit@example.com")
    created = await _create_integration(client, headers)
    config_id = created.json()["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"2" * 48
    seen: list[str] = []

    async def fake_edit(config, *, prompt, image, mask, size, n, quality=None, style=None):
        seen.append(f"edit:{prompt}:{image[0]}:{mask is not None}")
        return [(png, "image/png", "png")]

    async def fake_variation(config, *, image, size, n):
        seen.append(f"variation:{image[0]}")
        return [(png, "image/png", "png")]

    monkeypatch.setattr("app.routers.media.edit_images", fake_edit)
    monkeypatch.setattr("app.routers.media.variation_images", fake_variation)

    edited = await client.post(
        "/images/edits",
        data={"prompt": "make it blue", "size": "512x512", "n": "1", "integration_id": config_id},
        files={"image": ("source.png", png, "image/png")},
        headers=headers,
    )
    varied = await client.post(
        "/images/variations",
        data={"size": "512x512", "n": "1", "integration_id": config_id},
        files={"image": ("source.png", png, "image/png")},
        headers=headers,
    )
    assert edited.status_code == 201
    assert varied.status_code == 201
    assert seen[0] == "edit:make it blue:source.png:False"
    assert seen[1] == "variation:source.png"
    calls = await client.get("/integrations/calls?kind=image_generation", headers=headers)
    operations = {row["operation"] for row in calls.json()}
    assert "image_edit" in operations
    assert "image_variation" in operations

    bad = await client.post(
        "/images/edits",
        data={"prompt": "nope"},
        files={"image": ("source.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert bad.status_code == 415


async def test_image_analysis_with_vision_provider(
    client, api, registry, fake_provider
):
    from app.deps import get_scoped_registry
    from app.main import app as app_instance
    from app.providers.registry import ProviderRegistry

    headers = await api.headers("p12-s9-image-analyze@example.com")
    fake_provider.complete_content = "A blue square."
    app_instance.dependency_overrides[get_scoped_registry] = lambda: ProviderRegistry(
        {"fake": fake_provider}
    )
    try:
        response = await client.post(
            "/images/analyze",
            data={
                "question": "What is in this image?",
                "provider_id": "fake",
                "model": "fake-model",
            },
            files={
                "file": (
                    "image.png",
                    b"\x89PNG\r\n\x1a\n" + b"3" * 16,
                    "image/png",
                )
            },
            headers=headers,
        )
    finally:
        app_instance.dependency_overrides.pop(get_scoped_registry, None)

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "A blue square."
    assert body["provider_id"] == "fake"
    assert fake_provider.complete_calls
    content = fake_provider.complete_calls[-1][0][-1].content
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"


async def test_audio_transcription_and_speech(client, api, monkeypatch):
    headers = await api.headers("p12-s9-audio@example.com")
    await _create_integration(client, headers, kind="stt", name="STT", model="whisper-1")
    await _create_integration(
        client,
        headers,
        kind="tts",
        name="TTS",
        model="tts-1",
        options={"voice": "alloy"},
    )

    async def fake_transcribe(config, *, filename, content, content_type, language, prompt):
        assert filename == "clip.wav"
        assert content.startswith(b"RIFF")
        return "transcribed text"

    async def fake_speech(config, *, text, voice, response_format, speed):
        assert text == "hello world"
        return b"ID3fakeaudio", "audio/mpeg"

    monkeypatch.setattr("app.routers.audio.transcribe_audio", fake_transcribe)
    monkeypatch.setattr("app.routers.audio.synthesize_speech", fake_speech)

    transcribed = await client.post(
        "/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFF0000", "audio/wav")},
        headers=headers,
    )
    assert transcribed.status_code == 200
    assert transcribed.json()["text"] == "transcribed text"

    speech = await client.post(
        "/audio/speech",
        json={"text": "hello world", "response_format": "mp3"},
        headers=headers,
    )
    assert speech.status_code == 200
    assert speech.headers["content-type"] == "audio/mpeg"
    assert speech.content == b"ID3fakeaudio"

    calls = await client.get("/integrations/calls", headers=headers)
    operations = {(row["operation"], row["kind"]) for row in calls.json()}
    assert ("stt", "stt") in operations
    assert ("tts", "tts") in operations


async def test_audio_rejects_unsupported_file(client, api):
    headers = await api.headers("p12-s9-audio-bad@example.com")
    await _create_integration(client, headers, kind="stt", name="STT")
    response = await client.post(
        "/audio/transcriptions",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_audio_type"


async def test_github_read_only_connector(client, api, monkeypatch):
    headers = await api.headers("p12-s9-github@example.com")
    bob = await api.headers("p12-s9-github-bob@example.com")
    created = await _create_integration(
        client,
        headers,
        kind="github",
        provider="github",
        credential="ghp_test",
        name="GitHub",
        model="",
    )
    config_id = created.json()["id"]

    async def fake_repos(config):
        return [
            {
                "full_name": "acme/demo",
                "description": "Demo",
                "private": False,
                "html_url": "https://github.com/acme/demo",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]

    async def fake_issues(config, *, owner, repo, state):
        assert (owner, repo, state) == ("acme", "demo", "open")
        return [
            {
                "number": 1,
                "title": "Issue",
                "state": "open",
                "html_url": "https://github.com/acme/demo/issues/1",
                "created_at": None,
                "updated_at": None,
            }
        ]

    monkeypatch.setattr("app.routers.connectors.list_github_repos", fake_repos)
    monkeypatch.setattr("app.routers.connectors.list_github_issues", fake_issues)

    repos = await client.get(
        f"/connectors/github/repos?integration_id={config_id}", headers=headers
    )
    issues = await client.get(
        f"/connectors/github/repos/acme/demo/issues?integration_id={config_id}",
        headers=headers,
    )
    assert repos.status_code == 200
    assert repos.json()[0]["full_name"] == "acme/demo"
    assert issues.status_code == 200
    assert issues.json()[0]["number"] == 1

    outsider = await client.get(
        f"/connectors/github/repos?integration_id={config_id}", headers=bob
    )
    assert outsider.status_code == 404