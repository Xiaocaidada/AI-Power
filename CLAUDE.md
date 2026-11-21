# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

P0 in progress. **S1 complete**: auth + per-user isolation. **S2 complete**: provider abstraction + SSE chat (`/providers`, `/conversations`, streaming messages). Next: S3 (document upload + async ingestion). See the capability contract before starting any slice.

## Documents

- [PRODUCT-BRIEF.md](./PRODUCT-BRIEF.md) — 产品诊断、路线图 P0–P3、反目标与成功指标。
- [docs/product/CAPABILITY.md](./docs/product/CAPABILITY.md) — P0 能力契约：API、状态机、数据模型、安全约束与开放问题。
- [docs/adr/0001-p0-stack.md](./docs/adr/0001-p0-stack.md) — 技术栈与模型接入决策（DeepSeek + 本地 Qwen、bge-m3 1024 维、幂等上传、本地 Compose）。
- [docs/tdd/p0-s1-auth.md](./docs/tdd/p0-s1-auth.md) — S1 的 RED/GREEN 证据与测试清单。
- [docs/tdd/p0-s2-provider-sse.md](./docs/tdd/p0-s2-provider-sse.md) — S2 的 RED/GREEN 证据、SSE 契约与真实模型冒烟。

## Commands

All Python commands use the project venv. On Windows that is `.venv/Scripts/python.exe`.

- Setup: `uv venv --python 3.13 .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`
- Run tests: `.venv/Scripts/python.exe -m pytest`
- Run one test: `.venv/Scripts/python.exe -m pytest tests/test_conversations.py::test_send_message_streams_and_persists`
- Coverage: `.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing`
- Lint: `.venv/Scripts/python.exe -m ruff check .`
- Format: `.venv/Scripts/python.exe -m ruff format .`
- Run app: `.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000`
- Postgres + Redis: `docker compose up -d postgres redis` (Docker runs in WSL; the current Git Bash may not expose `docker` on PATH)

## Architecture

- **Layering**: `app/routers/*` (HTTP) → `app/deps.py` (auth + provider registry dependencies) → `app/models.py` (SQLAlchemy) / `app/schemas.py` (Pydantic) / `app/security.py` (argon2 + JWT). `app/db.py` owns the async engine and session factory; `app/config.py` owns env-backed settings; `app/providers/` owns the LLM boundary.
- **Auth flow**: `POST /auth/register` hashes with argon2id; `POST /auth/login` returns an HS256 JWT (`sub` = user UUID, 24h TTL); every protected route resolves `User` via `HTTPBearer` in `app/deps.py`. Login uses a dummy hash for unknown emails so timing and error text do not reveal whether the account exists.
- **Provider boundary**: `LLMProvider` (`list_models`, `stream_chat`) is the only surface business code sees. `OpenAICompatProvider` implements DeepSeek / llama.cpp / vLLM using OpenAI Chat Completions; `ProviderRegistry` builds instances from settings. Streaming requests send `stream_options.include_usage=true`; usage is still stored as nullable.
- **Chat flow**: `POST /conversations/{id}/messages` validates ownership, persists the user message and an assistant message with `status="streaming"`, then returns `StreamingResponse` (`text/event-stream`). Events are `meta → delta* → usage → done`, or a terminal `error`. The generator finalizes the assistant message in a **fresh** `SessionLocal` session (`completed` / `cancelled` / `failed`, content + tokens) because the request-scoped session is not safe to hold inside a streaming response.
- **Isolation invariant**: every user-owned query filters by `user_id`; cross-user access returns **404, not 403**. Knowledge bases use soft delete (`deleted_at`); conversations use archival (`archived_at`).
- **Persistence**: dev/tests use SQLite (`aiosqlite`, `NullPool`); production P0 targets Postgres + pgvector via `DATABASE_URL`. Tables are created by `init_db()` on app lifespan; **Alembic has not been introduced yet**.
- **Tests**: `tests/conftest.py` sets `DATABASE_URL`/`JWT_SECRET` before importing the app, recreates the schema per test, and drives the ASGI app with `httpx.ASGITransport`. Conversation tests override `get_registry` with an in-memory fake provider. Coverage requires `concurrency = ["greenlet", "thread"]`.
- **External model services** (OpenAI-compatible, configured in `.env`): local Qwen `http://192.168.29.100:8083/v1` (llama.cpp, context 16384), bge-m3 `http://192.168.29.100:8000/v1` (vLLM, 1024 dimensions), DeepSeek `https://api.deepseek.com`.

## Conventions

- Tests first: write the failing test, run it, then implement. Keep the RED/GREEN evidence in `docs/tdd/`.
- Any new user-owned resource must filter by `user_id` and return 404 on cross-user access; add an isolation test with two users.
- SSE event contract is fixed: `meta`, `delta`, `usage`, `done`, `error`; `error` is terminal. Do not add events without updating `CAPABILITY.md` and the S2 tests.
- Provider code must not import vendor SDKs outside `app/providers/`; API keys come from settings/env only.
- Never log `Authorization`, provider API keys, or full document text. `APP_ENV != dev` rejects a `dev-` JWT secret.
- Windows-specific path: use `.venv/Scripts/python.exe` (not `.venv/bin/python`).