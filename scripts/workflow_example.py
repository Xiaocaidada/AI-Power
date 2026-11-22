"""Run a minimal workflow through the public API.

Reads credentials from the environment and never prints them:

    AI_POWER_BASE_URL=http://192.168.29.100:8080/api
    AI_POWER_EMAIL=demo@example.com
    AI_POWER_PASSWORD=...

Example:
    python scripts/workflow_example.py --provider local-qwen --model qwen2.5-7b-instruct
"""

import argparse
import json
import os

import httpx

WORKFLOW_NAME = "CLI Demo"


def definition(provider_id: str, model: str) -> dict[str, object]:
    return {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "config": {
                    "provider_id": provider_id,
                    "model": model,
                    "prompt": "Answer concisely: {{input}}",
                },
            }
        ],
        "edges": [],
    }


def login(client: httpx.Client, base: str) -> str:
    email = os.environ.get("AI_POWER_EMAIL", "").strip()
    password = os.environ.get("AI_POWER_PASSWORD", "")
    if not email or not password:
        raise SystemExit("set AI_POWER_EMAIL and AI_POWER_PASSWORD")
    client.post(f"{base}/auth/register", json={"email": email, "password": password})
    response = client.post(f"{base}/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def find_or_create_workflow(
    client: httpx.Client, base: str, headers: dict[str, str], provider_id: str, model: str
) -> str:
    workflows = client.get(f"{base}/workflows", headers=headers)
    workflows.raise_for_status()
    for workflow in workflows.json():
        if workflow["name"] == WORKFLOW_NAME:
            return workflow["id"]
    created = client.post(
        f"{base}/workflows",
        headers=headers,
        json={
            "name": WORKFLOW_NAME,
            "description": "Created by scripts/workflow_example.py",
            "definition": definition(provider_id, model),
        },
    )
    created.raise_for_status()
    return created.json()["id"]


def run(
    client: httpx.Client, base: str, headers: dict[str, str], workflow_id: str, prompt: str
) -> None:
    created = client.post(
        f"{base}/workflows/{workflow_id}/runs",
        headers=headers,
        json={"input": prompt},
    )
    created.raise_for_status()
    run_id = created.json()["run_id"]
    print(f"run {run_id}: {created.json()['status']}")
    event = None
    with client.stream(
        "GET",
        f"{base}/workflows/runs/{run_id}/events",
        headers=headers,
        params={"after": 0},
        timeout=180,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                if event == "node_end":
                    print(
                        f"node {data['node_id']}: {data['status']} ({data.get('duration_ms')} ms)"
                    )
                elif event == "workflow_end":
                    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AI_POWER_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", default="用一句话介绍这个平台")
    args = parser.parse_args()

    with httpx.Client(timeout=30) as client:
        token = login(client, args.base_url)
        headers = {"Authorization": f"Bearer {token}"}
        workflow_id = find_or_create_workflow(
            client, args.base_url, headers, args.provider, args.model
        )
        run(client, args.base_url, headers, workflow_id, args.input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
