# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

P0 in progress. **S1 complete**: auth (register/login/me) + per-user isolation for knowledge bases. Next: S2 (provider abstraction + SSE streaming). See the capability contract before starting any slice.

## Documents

- [PRODUCT-BRIEF.md](./PRODUCT-BRIEF.md) — 产品诊断、路线图 P0–P3、反目标与成功指标。
- [docs/product/CAPABILITY.md](./docs/product/CAPABILITY.md) — P0 能力契约：API、状态机、数据模型、安全约束与开放问题。
- [docs/adr/0001-p0-stack.md](./docs/adr/0001-p0-stack.md) — 技术栈与模型接入决策（DeepSeek + 本地 Qwen、bge-m3 1024 维、幂等上传、本地 Compose）。
- [docs/tdd/p0-s1-auth.md](./docs/tdd/p0-s1-auth.md) — S1 的 RED/GREEN 证据与测试清单。

## Commands

All Python commands use the project venv. On Windows that is `.venv/Scripts/python.exe`.

- Setup: `uv venv --python 3.13 .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`
- Run tests: `.venv/Scripts/python.exe -m pytest`
- Run one test: `.venv/Scripts/python.exe -m pytest tests/test_auth.py::test_login_returns_bearer_token`
- Coverage: `.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing`
- Lint: `.venv/Scripts/python.exe -m ruff check .`
- Format: `.venv/Scripts/python.exe -m ruff format .`
- Run app: `.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000`
- Postgres + Redis: `docker compose up -d postgres redis` (Docker is **not** installed on the current dev machine)

## Architecture

- **Layering**: `app/routers/*` (HTTP) → `app/deps.py` (auth dependency) → `app/models.py` (SQLAlchemy) / `app/schemas.py` (Pydantic) / `app/security.py` (argon2 + JWT). `app/db.py` owns the async engine and session factory; `app/config.py` owns env-backed settings.
- **Auth flow**: `POST /auth/register` hashes with argon2id; `POST /auth/login` returns an HS256 JWT (`sub` = user UUID, 24h TTL); every protected route resolves `User` via `HTTPBearer` in `app/deps.py`. Login uses a dummy hash for unknown emails so timing and error text do not reveal whether the account exists.
- **Isolation invariant**: every user-owned query filters by `user_id`; cross-user access returns **404, not 403** (avoids enumeration). Knowledge bases use soft delete (`deleted_at`) and all reads exclude deleted rows.
- **Persistence**: dev/tests use SQLite (`aiosqlite`, `NullPool`); production P0 targets Postgres + pgvector via `DATABASE_URL`. Tables are created by `init_db()` on app lifespan; **Alembic has not been introduced yet**.
- **Tests**: `tests/conftest.py` sets `DATABASE_URL`/`JWT_SECRET` before importing the app, recreates the schema per test, and drives the ASGI app with `httpx.ASGITransport`. Coverage requires `concurrency = ["greenlet", "thread"]` in `pyproject.toml` because SQLAlchemy async switches through greenlets.
- **External model services** (OpenAI-compatible, configured in `.env`): local Qwen `http://192.168.29.100:8083/v1` (llama.cpp), bge-m3 `http://192.168.29.100:8000/v1` (vLLM, 1024 dimensions), DeepSeek `https://api.deepseek.com`. The local llama.cpp build returns `usage`, but provider usage must still be treated as nullable.

## Conventions

- Tests first: write the failing test, run it, then implement. Keep the RED/GREEN evidence in `docs/tdd/`.
- Any new user-owned resource must filter by `user_id` and return 404 on cross-user access; add an isolation test with two users.
- Secrets come from env only. Never log `Authorization`, provider API keys, or full document text. `APP_ENV != dev` rejects a `dev-` JWT secret.
- Windows-specific path: use `.venv/Scripts/python.exe` (not `.venv/bin/python`).