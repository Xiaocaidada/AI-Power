"""Concurrent workflow load test.

Creates one throwaway account and one single-node workflow, then runs it at a
fixed concurrency. Credentials are never printed.

Example:
    python scripts/loadtest_workflow.py --base-url http://192.168.29.100:8002 \
        --provider local-qwen --model qwen2.5-7b-instruct --concurrency 5
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


async def session(client: httpx.AsyncClient, base: str) -> dict[str, str]:
    email = f"wf-load-{uuid.uuid4().hex[:10]}@example.com"
    password = f"Load!{uuid.uuid4().hex[:12]}"
    await client.post(f"{base}/auth/register", json={"email": email, "password": password})
    login = await client.post(f"{base}/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def create_workflow(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    provider_id: str,
    model: str,
) -> str:
    definition = {
        "nodes": [
            {
                "id": "only",
                "type": "llm",
                "config": {
                    "provider_id": provider_id,
                    "model": model,
                    "prompt": "Answer in one short sentence: {{input}}",
                },
            }
        ],
        "edges": [],
    }
    created = await client.post(
        f"{base}/workflows",
        headers=headers,
        json={"name": "Load test", "definition": definition},
    )
    created.raise_for_status()
    return created.json()["id"]


async def one_run(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    workflow_id: str,
    prompt: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, object]:
    async with semaphore:
        started = time.perf_counter()
        status = "failed"
        tokens = 0
        async with client.stream(
            "POST",
            f"{base}/workflows/{workflow_id}/runs",
            headers=headers,
            json={"input": prompt},
        ) as response:
            response.raise_for_status()
            event = None
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event = line[len("event: ") :]
                elif line.startswith("data: ") and event == "workflow_end":
                    data = json.loads(line[len("data: ") :])
                    status = str(data.get("status", "failed"))
                    tokens = int(data.get("prompt_tokens", 0)) + int(
                        data.get("completion_tokens", 0)
                    )
        return {
            "status": status,
            "duration": time.perf_counter() - started,
            "tokens": tokens,
        }


async def main_async(args: argparse.Namespace) -> int:
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        headers = await session(client, args.base_url)
        workflow_id = await create_workflow(
            client, args.base_url, headers, args.provider, args.model
        )
        results = await asyncio.gather(
            *[
                one_run(
                    client,
                    args.base_url,
                    headers,
                    workflow_id,
                    args.prompt,
                    semaphore,
                )
                for _ in range(args.requests)
            ]
        )
    durations = [float(item["duration"]) for item in results]
    ok = sum(1 for item in results if item["status"] == "completed")
    print(f"requests={len(results)} concurrency={args.concurrency} ok={ok}")
    print(
        "duration_ms "
        f"p50={percentile(durations, 0.5) * 1000:.0f} "
        f"p95={percentile(durations, 0.95) * 1000:.0f} "
        f"mean={statistics.mean(durations) * 1000:.0f}"
    )
    print(f"tokens={sum(int(item['tokens']) for item in results)}")
    return 0 if ok == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--requests", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--prompt", default="请用一句话介绍你自己")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
