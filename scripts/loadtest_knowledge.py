"""Knowledge retrieval concurrency load test.

Creates a throwaway account, one knowledge base and one small document, waits for
ingestion, then measures concurrent retrieval latency. Credentials are generated
per run and never printed.

Example:
    python scripts/loadtest_knowledge.py --base-url http://192.168.29.100:8002 \
        --concurrency 10 --requests 50
"""

import argparse
import asyncio
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


async def login(client: httpx.AsyncClient, base: str, email: str, password: str) -> str:
    await client.post(
        f"{base}/auth/register", json={"email": email, "password": password}
    )
    response = await client.post(
        f"{base}/auth/login", json={"email": email, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def wait_ready(
    client: httpx.AsyncClient, base: str, headers: dict[str, str], document_id: str
) -> None:
    for _ in range(120):
        response = await client.get(f"{base}/documents/{document_id}", headers=headers)
        response.raise_for_status()
        if response.json()["status"] == "ready":
            return
        if response.json()["status"] == "failed":
            raise SystemExit("document ingestion failed")
        await asyncio.sleep(0.5)
    raise SystemExit("document ingestion timed out")


async def search(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    kb_id: str,
    query: str,
    semaphore: asyncio.Semaphore,
) -> float | None:
    async with semaphore:
        started = time.perf_counter()
        response = await client.post(
            f"{base}/knowledge-bases/{kb_id}/retrieval/search",
            headers=headers,
            json={"query": query, "top_k": 5},
        )
        elapsed = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            return None
        return elapsed


async def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge retrieval load test")
    parser.add_argument("--base-url", default="http://192.168.29.100:8002")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--query", default="alpha beta")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    email = f"loadtest-kb-{uuid.uuid4().hex[:12]}@example.com"
    password = f"Lt-{uuid.uuid4().hex[:16]}"

    async with httpx.AsyncClient(timeout=60) as client:
        token = await login(client, base, email, password)
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            f"{base}/knowledge-bases", headers=headers, json={"name": "Load test KB"}
        )
        created.raise_for_status()
        kb_id = created.json()["id"]
        uploaded = await client.post(
            f"{base}/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={
                "file": (
                    "loadtest.txt",
                    b"alpha beta gamma delta epsilon zeta eta theta",
                    "text/plain",
                )
            },
        )
        uploaded.raise_for_status()
        await wait_ready(client, base, headers, uploaded.json()["id"])
        print(f"ready: kb={kb_id} concurrency={args.concurrency} requests={args.requests}")

        semaphore = asyncio.Semaphore(max(args.concurrency, 1))
        started = time.perf_counter()
        latencies = await asyncio.gather(
            *[
                search(client, base, headers, kb_id, args.query, semaphore)
                for _ in range(args.requests)
            ]
        )
        wall = (time.perf_counter() - started) * 1000
        values = [value for value in latencies if value is not None]
        errors = len(latencies) - len(values)
        print(f"wall_ms={wall:.1f}")
        print(f"requests={len(latencies)} ok={len(values)} errors={errors}")
        if values:
            print(f"latency_p50_ms={percentile(values, 0.5):.1f}")
            print(f"latency_p95_ms={percentile(values, 0.95):.1f}")
            print(f"latency_mean_ms={statistics.fmean(values):.1f}")
            print(f"throughput_rps={len(values) / (wall / 1000):.2f}")


if __name__ == "__main__":
    asyncio.run(main())