import json

from app.services.web_search import WebResult

PLAN = json.dumps(
    {
        "title": "Qwen 技术研究",
        "steps": [
            {"title": "背景与现状", "query": "qwen background"},
            {"title": "对比与争议", "query": "qwen comparison"},
        ],
    }
)
STEP = json.dumps(
    {
        "summary": "该步骤的主要发现来自来源 [1]。",
        "claims": [{"text": "存在可核验事实", "sources": [1]}],
    }
)
REPORT = json.dumps(
    {
        "agreements": ["来源在基本事实上一致"],
        "conflicts": [],
        "sections": {
            "background": "背景 [1]，伪造引用 [99]。",
            "method": "执行两步检索 [1]。",
            "findings": "主要发现 [1]。",
            "comparison": "未发现冲突 [1]。",
            "conclusion": "结论仅覆盖已列来源 [1]。",
        },
    }
)


async def _search_provider(client, headers):
    return await client.post(
        "/search-providers",
        json={
            "provider": "searxng",
            "name": "Test search",
            "base_url": "http://searx.local",
            "max_results": 5,
        },
        headers=headers,
    )


def _fake_search(monkeypatch):
    calls: list[str] = []

    async def search(config, query, *, max_results=None, client=None):
        calls.append(query)
        slug = abs(hash(query)) % 100000
        return [
            WebResult(
                title=f"Result for {query}",
                url=f"https://example.com/{slug}",
                site="example.com",
                snippet=f"Evidence about {query}",
                published_at="2026-01-01",
            )
        ]

    monkeypatch.setattr("app.services.research.search_web", search)
    return calls


async def test_research_plan_confirmation_execution_and_report(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-flow@example.com")
    search = await _search_provider(client, headers)
    assert search.status_code == 201
    _fake_search(monkeypatch)
    fake_provider.complete_contents = [PLAN, STEP, STEP, REPORT]

    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构与争议",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )

    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["status"] == "waiting_approval"
    assert created.json()["plan"]["confirmed"] is False
    assert len(created.json()["plan"]["steps"]) == 2

    edited = await client.patch(
        f"/research/tasks/{task_id}/plan",
        json={
            "steps": [
                {"title": "背景与现状", "query": "qwen background"},
                {"title": "对比与争议", "query": "qwen comparison"},
            ]
        },
        headers=headers,
    )
    assert edited.status_code == 200

    confirmed = await client.post(f"/research/tasks/{task_id}/confirm", headers=headers)
    assert confirmed.status_code == 200

    detail = await client.get(f"/research/tasks/{task_id}", headers=headers)
    body = detail.json()
    assert body["status"] == "completed"
    assert body["plan"]["confirmed"] is True
    assert body["result"]["report"].startswith("# Qwen 技术研究")
    assert "## 背景" in body["result"]["report"]
    assert "[99]" not in body["result"]["report"]
    assert "https://example.com/" in body["result"]["report"]
    assert body["result"]["sources"][0]["kind"] == "web"
    assert body["result"]["step_summaries"][0]["summary"].startswith("该步骤")

    events = await client.get(f"/chat-tasks/{task_id}/events?after=0", headers=headers)
    names = [
        line.split("event: ", 1)[1]
        for line in events.text.splitlines()
        if line.startswith("event: ")
    ]
    assert "research_plan_created" in names
    assert "research_plan_confirmed" in names
    assert names.count("research_step_started") == 2
    assert "research_report_ready" in names
    assert "task_completed" in names


async def test_research_in_conversation_appends_report_message(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-chat@example.com")
    search = await _search_provider(client, headers)
    _fake_search(monkeypatch)
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    fake_provider.complete_contents = [PLAN, STEP, STEP, REPORT]

    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "conversation_id": conversation.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )
    await client.post(f"/research/tasks/{created.json()['id']}/confirm", headers=headers)

    detail = await client.get(
        f"/conversations/{conversation.json()['id']}", headers=headers
    )
    assistant = [item for item in detail.json()["messages"] if item["role"] == "assistant"]
    assert assistant[-1]["mode"] == "deep_research"
    assert assistant[-1]["mode_meta"]["research_task_id"] == created.json()["id"]
    assert assistant[-1]["content"].startswith("# Qwen 技术研究")
    assert len(assistant[-1]["web_sources"]) >= 1


async def test_research_followup_save_to_knowledge_and_isolation(
    client, api, registry, fake_provider, fake_ingestion, monkeypatch
):
    headers = await api.headers("p12-s6-reuse@example.com")
    bob = await api.headers("p12-s6-bob@example.com")
    search = await _search_provider(client, headers)
    _fake_search(monkeypatch)
    fake_provider.complete_contents = [PLAN, STEP, STEP, REPORT]
    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )
    task_id = created.json()["id"]
    await client.post(f"/research/tasks/{task_id}/confirm", headers=headers)

    fake_provider.complete_content = "根据报告，结论是 [1]。"
    followup = await client.post(
        f"/research/tasks/{task_id}/followup",
        json={"question": "结论是什么？"},
        headers=headers,
    )
    assert followup.status_code == 200
    assert followup.json()["answer"].startswith("根据报告")

    kb = await client.post("/knowledge-bases", json={"name": "研究库"}, headers=headers)
    saved = await client.post(
        f"/research/tasks/{task_id}/save-to-knowledge",
        json={"kb_id": kb.json()["id"], "title": "研究报告"},
        headers=headers,
    )
    duplicate = await client.post(
        f"/research/tasks/{task_id}/save-to-knowledge",
        json={"kb_id": kb.json()["id"], "title": "研究报告"},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["document_id"] == saved.json()["document_id"]

    outsider = await client.get(f"/research/tasks/{task_id}", headers=bob)
    assert outsider.status_code == 404


async def test_research_llm_limit_fails_typed(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-limit@example.com")
    search = await _search_provider(client, headers)
    _fake_search(monkeypatch)
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "research_max_llm_calls", 1)
    fake_provider.complete_contents = [PLAN, STEP]

    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )
    await client.post(f"/research/tasks/{created.json()['id']}/confirm", headers=headers)

    detail = await client.get(f"/research/tasks/{created.json()['id']}", headers=headers)
    assert detail.json()["status"] == "failed"
    assert detail.json()["error_code"] == "research_llm_limit"
    assert detail.json()["checkpoint"]["completed_steps"] == 1
    assert detail.json()["plan"]["steps"][0]["status"] == "done"
    assert detail.json()["plan"]["steps"][1]["status"] == "failed"
    assert detail.json()["plan"]["steps"][1]["error_code"] == "research_llm_limit"


async def test_research_source_limit_fails_typed(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-source-limit@example.com")
    search = await _search_provider(client, headers)

    async def many_results(config, query, *, max_results=None, client=None):
        return [
            WebResult(
                title=f"{query} {index}",
                url=f"https://example.com/{abs(hash(query))}-{index}",
                site="example.com",
                snippet="evidence",
                published_at=None,
            )
            for index in range(5)
        ]

    monkeypatch.setattr("app.services.research.search_web", many_results)
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "research_max_sources", 3)
    fake_provider.complete_contents = [PLAN]
    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )
    await client.post(f"/research/tasks/{created.json()['id']}/confirm", headers=headers)
    detail = await client.get(f"/research/tasks/{created.json()['id']}", headers=headers)
    assert detail.json()["status"] == "failed"
    assert detail.json()["error_code"] == "research_source_limit"
    assert detail.json()["plan"]["steps"][0]["status"] == "failed"
    assert detail.json()["plan"]["steps"][0]["error_code"] == "research_source_limit"


async def test_research_requires_confirmation_before_execution(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-confirm@example.com")
    search = await _search_provider(client, headers)
    calls = _fake_search(monkeypatch)
    fake_provider.complete_contents = [PLAN]

    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )
    assert created.json()["status"] == "waiting_approval"
    assert calls == []
    assert len(fake_provider.complete_contents) == 0

    detail = await client.get(f"/research/tasks/{created.json()['id']}", headers=headers)
    assert detail.json()["status"] == "waiting_approval"
    assert detail.json()["result"] == {}


async def test_deep_research_chat_mode_creates_plan(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-mode@example.com")
    search = await _search_provider(client, headers)
    _fake_search(monkeypatch)
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    fake_provider.complete_contents = [PLAN]

    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={
            "content": "研究 Qwen 的架构",
            "mode": "deep_research",
            "mode_meta": {"search_provider_id": search.json()["id"]},
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert "event: research_plan" in response.text
    assert "event: stage" in response.text
    tasks = await client.get(
        f"/research/tasks?conversation_id={conversation.json()['id']}", headers=headers
    )
    assert tasks.json()[0]["status"] == "waiting_approval"
    detail = await client.get(
        f"/conversations/{conversation.json()['id']}", headers=headers
    )
    assistant = [item for item in detail.json()["messages"] if item["role"] == "assistant"]
    assert assistant[-1]["mode"] == "deep_research"
    assert assistant[-1]["mode_meta"]["research_task_id"] == tasks.json()[0]["id"]


async def test_research_plan_edit_locked_after_confirmation(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s6-locked@example.com")
    search = await _search_provider(client, headers)
    _fake_search(monkeypatch)
    fake_provider.complete_contents = [PLAN, STEP, STEP, REPORT]
    created = await client.post(
        "/research/tasks",
        json={
            "topic": "Qwen 的架构",
            "provider_id": "fake",
            "model": "fake-model",
            "scope": "web",
            "search_provider_id": search.json()["id"],
            "max_steps": 3,
        },
        headers=headers,
    )
    task_id = created.json()["id"]
    await client.post(f"/research/tasks/{task_id}/confirm", headers=headers)

    locked = await client.patch(
        f"/research/tasks/{task_id}/plan",
        json={"steps": [{"title": "新步骤", "query": "new query"}]},
        headers=headers,
    )
    assert locked.status_code == 409
    assert locked.json()["detail"]["code"] == "plan_locked"