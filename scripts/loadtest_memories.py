"""Memory retrieval and graph concurrency load test.

Creates a throwaway account, seeds memories, then measures concurrent list/graph
latency. Credentials are generated per run and never printed.

Example:
    python scripts/loadtest_memories.py --base-url http://192.168.29.100:8002 \
        --concurrency 10 --requests 50 --memories 60
"""

import argparse
import asyncio
import statistics
import time
import uuid

import httpx

TOPICS = (
    ("preference", "回答风格", "Prefers concise answers for release notes."),
    ("technical", "数据库选择", "The billing service uses PostgreSQL for storage."),
    ("project", "发布计划", "The release plan ships on Friday after smoke tests."),
    ("decision", "模型路由", "Model routing prefers the local provider first."),
    ("experience", "排查经验", "Slow ingestion was caused by missing pgvector indexes."),
)


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


async def seed(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    count: int,
) -> None:
    for index in range(count):
        category, title, content = TOPICS[index % len(TOPICS)]
        response = await client.post(
            f"{base}/memories",
            headers=headers,
            json={
                "title": f"{title} {index}",
                "content": f"{content} Variant {index}.",
                "category": category,
                "tags": ["loadtest", category],
            },
        )
        response.raise_for_status()


async def measure(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    path: str,
    semaphore: asyncio.Semaphore,
) -> tuple[float, bool]:
    async with semaphore:
        started = time.perf_counter()
        response = await client.get(f"{base}{path}", headers=headers)
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, response.status_code == 200


async def run_round(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    *,
    path: str,
    concurrency: int,
    requests: int,
    query: str,
) -> list[float]:
    separator = "&" if "?" in path else "?"
    full_path = f"{path}{separator}q={query}"
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *[
            measure(client, base, headers, full_path, semaphore)
            for _ in range(requests)
        ]
    )
    latencies = [elapsed for elapsed, ok in results if ok]
    failures = sum(1 for _, ok in results if not ok)
    print(
        f"{path}: success={len(latencies)}/{requests} failures={failures} "
        f"p50={percentile(latencies, 0.5):.1f}ms "
        f"p95={percentile(latencies, 0.95):.1f}ms "
        f"avg={statistics.mean(latencies) if latencies else 0:.1f}ms "
        f"max={max(latencies, default=0):.1f}ms"
    )
    return latencies


async def main() -> None:
    parser = argparse.ArgumentParser(description="Memory retrieval load test")
    parser.add_argument("--base-url", default="http://192.168.29.100:8002")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--memories", type=int, default=60)
    parser.add_argument("--query", default="concise")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    email = f"memory-load-{uuid.uuid4().hex[:12]}@example.com"
    password = uuid.uuid4().hex + "Aa1!"
    async with httpx.AsyncClient(timeout=60) as client:
        token = await login(client, base, email, password)
        headers = {"Authorization": f"Bearer {token}"}
        await seed(client, base, headers, args.memories)
        print(f"seeded {args.memories} memories")
        await run_round(
            client,
            base,
            headers,
            path="/memories",
            concurrency=args.concurrency,
            requests=args.requests,
            query=args.query,
        )
        await run_round(
            client,
            base,
            headers,
            path="/memories/graph",
            concurrency=args.concurrency,
            requests=max(1, args.requests // 2),
            query=args.query,
        )


if __name__ == "__main__":
    asyncio.run(main())