from uuid import UUID

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Chunk
from app.providers.base import ChatChunk, Usage

CONTENT = """这是一个可复用的回答。

```python
print("hello")
```

任务：
- [ ] 写测试
- [x] 初始化项目
- TODO: 发布版本
"""


async def _conversation(client, headers, **extra):
    return await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", **extra},
        headers=headers,
    )


async def _assistant_message(client, headers, fake_provider, content=CONTENT):
    conversation = await _conversation(client, headers)
    fake_provider.chunks = [
        ChatChunk(delta=content),
        ChatChunk(usage=Usage(prompt_tokens=2, completion_tokens=4)),
        ChatChunk(finish_reason="stop"),
    ]
    await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "生成成果"},
        headers=headers,
    )
    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    return conversation.json()["id"], detail.json()["messages"][1]["id"]


async def test_extract_code_blocks_and_task_candidates(client, api, registry, fake_provider):
    headers = await api.headers("p12-s4-extract@example.com")
    conversation_id, message_id = await _assistant_message(client, headers, fake_provider)

    blocks = await client.get(
        f"/conversations/{conversation_id}/messages/{message_id}/code-blocks",
        headers=headers,
    )
    tasks = await client.get(
        f"/conversations/{conversation_id}/messages/{message_id}/task-candidates",
        headers=headers,
    )

    assert blocks.status_code == 200
    assert blocks.json()[0]["language"] == "python"
    assert 'print("hello")' in blocks.json()[0]["code"]
    assert tasks.status_code == 200
    assert tasks.json() == [
        {"title": "写测试", "status": "todo"},
        {"title": "初始化项目", "status": "done"},
        {"title": "发布版本", "status": "todo"},
    ]


async def test_save_answer_to_knowledge_and_deduplicate(
    client, api, registry, fake_provider, fake_ingestion
):
    headers = await api.headers("p12-s4-save-kb@example.com")
    conversation_id, message_id = await _assistant_message(
        client, headers, fake_provider, content="可复用的知识回答"
    )
    kb = await client.post("/knowledge-bases", json={"name": "成果库"}, headers=headers)

    first = await client.post(
        f"/conversations/{conversation_id}/messages/{message_id}/save-to-knowledge",
        json={"kb_id": kb.json()["id"], "title": "成果文档"},
        headers=headers,
    )
    second = await client.post(
        f"/conversations/{conversation_id}/messages/{message_id}/save-to-knowledge",
        json={"kb_id": kb.json()["id"], "title": "成果文档"},
        headers=headers,
    )

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert second.json()["document_id"] == first.json()["document_id"]

    documents = await client.get(f"/knowledge-bases/{kb.json()['id']}/documents", headers=headers)
    assert documents.json()[0]["status"] == "ready"
    assert documents.json()[0]["filename"] == "成果文档.md"
    async with SessionLocal() as session:
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == UUID(first.json()["document_id"]))
        )
    assert chunk_count and chunk_count > 0


async def test_code_snippet_isolation(client, api, registry, fake_provider):
    alice = await api.headers("p12-s4-snippet-alice@example.com")
    bob = await api.headers("p12-s4-snippet-bob@example.com")
    conversation_id, message_id = await _assistant_message(client, alice, fake_provider)

    created = await client.post(
        "/code-snippets",
        json={
            "title": "Hello",
            "language": "python",
            "code": 'print("hello")',
            "conversation_id": conversation_id,
            "message_id": message_id,
        },
        headers=alice,
    )
    listed = await client.get("/code-snippets", headers=alice)
    bob_listed = await client.get("/code-snippets", headers=bob)
    bob_delete = await client.delete(f"/code-snippets/{created.json()['id']}", headers=bob)

    assert created.status_code == 201
    assert created.json()["language"] == "python"
    assert created.json()["message_id"] == message_id
    assert listed.json()[0]["title"] == "Hello"
    assert bob_listed.json() == []
    assert bob_delete.status_code == 404


async def test_project_task_status(client, api, registry, fake_provider):
    headers = await api.headers("p12-s4-tasks@example.com")
    conversation_id, message_id = await _assistant_message(client, headers, fake_provider)
    project = await client.post("/projects", json={"name": "任务项目"}, headers=headers)

    created = await client.post(
        "/project-tasks",
        json={
            "project_id": project.json()["id"],
            "conversation_id": conversation_id,
            "message_id": message_id,
            "tasks": [
                {"title": "写测试", "status": "todo", "priority": "high"},
                {"title": "初始化项目", "status": "done"},
            ],
        },
        headers=headers,
    )
    listed = await client.get(f"/project-tasks?project_id={project.json()['id']}", headers=headers)
    task_id = created.json()[0]["id"]
    patched = await client.patch(
        f"/project-tasks/{task_id}", json={"status": "doing"}, headers=headers
    )

    assert created.status_code == 201
    assert len(created.json()) == 2
    assert created.json()[0]["source_message_id"] == message_id
    assert len(listed.json()) == 2
    assert patched.status_code == 200
    assert patched.json()["status"] == "doing"


async def test_share_requires_workspace_membership_and_revocation(
    client, api, registry, fake_provider
):
    alice = await api.headers("p12-s4-share-alice@example.com")
    bob = await api.headers("p12-s4-share-bob@example.com")
    alice_workspaces = await client.get("/workspaces", headers=alice)
    alice_workspace_id = alice_workspaces.json()[0]["id"]
    bob_me = await client.get("/auth/me", headers=bob)
    conversation = await _conversation(client, alice)
    created = await client.post(
        f"/conversations/{conversation.json()['id']}/shares",
        json={"expires_in_days": 7},
        headers=alice,
    )
    token = created.json()["token"]

    outsider = await client.get(f"/shares/{token}", headers=bob)
    await client.post(
        f"/workspaces/{alice_workspace_id}/members",
        json={"email": bob_me.json()["email"]},
        headers=alice,
    )
    member = await client.get(f"/shares/{token}", headers=bob)
    shares = await client.get(f"/conversations/{conversation.json()['id']}/shares", headers=alice)
    revoked = await client.delete(
        f"/conversations/{conversation.json()['id']}/shares/{created.json()['id']}",
        headers=alice,
    )
    after_revoke = await client.get(f"/shares/{token}", headers=bob)

    assert outsider.status_code == 404
    assert member.status_code == 200
    assert member.json()["id"] == conversation.json()["id"]
    assert shares.json()[0]["active"] is True
    assert revoked.status_code == 204
    assert after_revoke.status_code == 404
