# AI Power Python SDK

Typed sync/async client for the AI Power API. Install from the repo:

```bash
pip install -e sdk/python
```

## Chat (SSE)

```python
from ai_power_sdk import AIPowerClient

with AIPowerClient("http://192.168.29.100:8080/api") as client:
    client.login("demo@example.com", "password")
    conversation = client.create_conversation(provider_id="auto", model="auto")
    for event in client.chat_stream(conversation["id"], "你好"):
        if event.event == "delta":
            print(event.json().get("text", ""), end="")
```

## Knowledge base

```python
kb = client.create_knowledge_base("产品文档")
document = client.upload_document(kb["id"], "manual.md", open("manual.md", "rb").read())
client.wait_document(document["id"])
hits = client.retrieval_search(kb["id"], "退款多久到账", top_k=5)
```

## Workflow / collaboration

```python
for event in client.workflow_run("workflow-id", "总结这份资料"):
    print(event.event, event.json())
```

## Async

```python
from ai_power_sdk import AsyncAIPowerClient

async with AsyncAIPowerClient("http://192.168.29.100:8080/api") as client:
    await client.login("demo@example.com", "password")
    async for event in client.chat_stream("conversation-id", "你好"):
        ...
```

API-key mode: `AIPowerClient(base_url, api_key="ap_...")`. Keys need the matching scope
(`chat:write`, `kb:read`, or `workflow:run`).

Errors raise `AIPowerError` with `status_code`, `code`, `message`, `request_id`, and `body`.
GET requests retry 429/5xx up to two times; streaming requests are never retried.