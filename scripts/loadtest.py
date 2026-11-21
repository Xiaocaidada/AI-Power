"""Streaming concurrency load test.

Creates one throwaway account per run, one conversation per request, and measures
time-to-first-token (TTFT) and total latency at a fixed concurrency. Tokens are
summed from the SSE usage event; credentials are never printed.

Example:
    python scripts/loadtest.py --base-url http://192.168.29.100:8002 \
        --concurrency 20 --prompt "请用一句话介绍你自己"
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


async def create_session(client: httpx.AsyncClient, base: str, email: str, password: str) -> str:
    await client.post(f"{base}/auth/register", json={"email": email, "password": password})
    login = await client.post(f"{base}/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    return login.json()["access_token"]


async def pick_model(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    provider_id: str | None,
    model: str | None,
) -> tuple[str, str]:
    response = await client.get(f"{base}/providers", headers=headers)
    response.raise_for_status()
    available = [
        provider for provider in response.json() if provider["available"] and provider["models"]
    ]
    if not available:
        raise SystemExit("no available provider")
    provider = next(
        (item for item in available if item["id"] == provider_id),
        available[0],
    )
    return provider["id"], model or provider["models"][0]


async def run_stream(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    conversation_id: str,
    prompt: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, float]:
    async with semaphore:
        started = time.perf_counter()
        ttft: float | None = None
        usage: dict[str, object] = {}
        event = None
        async with client.stream(
            "POST",
            f"{base}/conversations/{conversation_id}/messages",
            headers=headers,
            json={"content": prompt},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    if event == "delta" and ttft is None:
                        ttft = (time.perf_counter() - started) * 1000
                    elif event == "usage":
                        usage = data
                    elif event == "error":
                        raise RuntimeError(data.get("code", "stream_error"))
        total = (time.perf_counter() - started) * 1000
        return {
            "ttft_ms": ttft if ttft is not None else total,
            "total_ms": total,
            "prompt_tokens": usage.get("prompt_tokens") or 0,
            "completion_tokens": usage.get("completion_tokens") or 0,
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Streaming concurrency load test")
    parser.add_argument("--base-url", default="http://192.168.29.100:8002")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--prompt", default="请用一句话介绍你自己")
    parser.add_argument("--provider-id", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout, connect=10.0)) as client:
        email = f"loadtest-{uuid.uuid4().hex[:8]}@example.com"
        token = await create_session(client, base, email, "Loadtest!pass123")
        headers = {"Authorization": f"Bearer {token}"}
        provider_id, model = await pick_model(client, base, headers, args.provider_id, args.model)

        conversations: list[str] = []
        for _ in range(args.concurrency):
            response = await client.post(
                f"{base}/conversations",
                headers=headers,
                json={"provider_id": provider_id, "model": model, "kb_id": None},
            )
            response.raise_for_status()
            conversations.append(response.json()["id"])

        semaphore = asyncio.Semaphore(args.concurrency)
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                run_stream(client, base, headers, conversation_id, args.prompt, semaphore)
                for conversation_id in conversations
            ),
            return_exceptions=True,
        )
        wall_seconds = time.perf_counter() - started

    errors = [item for item in results if isinstance(item, BaseException)]
    successes = [item for item in results if not isinstance(item, BaseException)]

    print(
        f"provider={provider_id} model={model} concurrency={args.concurrency} "
        f"wall_s={wall_seconds:.1f}"
    )
    print(f"ok={len(successes)} errors={len(errors)}")

    if successes:
        ttfts = [item["ttft_ms"] for item in successes]
        totals = [item["total_ms"] for item in successes]
        prompt_tokens = sum(item["prompt_tokens"] for item in successes)
        completion_tokens = sum(item["completion_tokens"] for item in successes)
        print(
            f"ttft_ms p50={statistics.median(ttfts):.0f} "
            f"p95={percentile(ttfts, 0.95):.0f} max={max(ttfts):.0f}"
        )
        print(
            f"total_ms p50={statistics.median(totals):.0f} "
            f"p95={percentile(totals, 0.95):.0f} max={max(totals):.0f}"
        )
        print(f"tokens prompt={prompt_tokens} completion={completion_tokens}")

    for error in errors[:5]:
        print(f"error: {type(error).__name__}: {error}")


if __name__ == "__main__":
    asyncio.run(main())
