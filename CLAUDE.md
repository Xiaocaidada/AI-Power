# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

P0 in progress. **S1 complete**: auth + per-user isolation. **S2 complete**: provider abstraction + SSE chat. **S3 complete**: document upload + async ingestion (PDF/MD/TXT → chunks → bge-m3 → pgvector). Next: S4 (retrieval + citations). See the capability contract before starting any slice.

## Documents

- [PRODUCT-BRIEF.md](./PRODUCT-BRIEF.md) — 产品诊断、路线图 P0–P3、反目标与成功指标。
- [docs/product/CAPABILITY.md](./docs/product/CAPABILITY.md) — P0 能力契约：API、状态机、数据模型、安全约束与开放问题。
- [docs/adr/0001-p0-stack.md](./docs/adr/0001-p0-stack.md) — 技术栈与模型接入决策。
- [docs/adr/0002-ingestion.md](./docs/adr/0002-ingestion.md) — 入库执行器、pgvector、分块、幂等与失败码。
- [docs/tdd/p0-s1-auth.md](./docs/tdd/p0-s1-auth.md) — S1 的 RED/GREEN 证据。
- [docs/tdd/p0-s2-provider-sse.md](./docs/tdd/p0-s2-provider-sse.md) — S2 的 SSE 契约与真实模型冒烟。
- [docs/tdd/p0-s3-ingestion.md](./docs/tdd/p0-s3-ingestion.md) — S3 的入库状态机、真实 bge-m3 与 pgvector 证据。

## Commands

All Python commands use the project venv. On Windows that is `.venv/Scripts/python.exe`.

- Setup: `uv venv --python 3.13 .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`
- Run tests: `.venv/Scripts/python.exe -m pytest`
- Run one test: `.venv/Scripts/python.exe -m pytest tests/test_documents.py::test_upload_ingests_and_marks_ready`
- Coverage: `.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing`
- Lint: `.venv/Scripts/python.exe -m ruff check .`
- Format: `.venv/Scripts/python.exe -m ruff format .`
- Run app: `.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000`
- Postgres + Redis: `docker compose up -d postgres redis` (Docker runs in WSL; use host `192.168.29.100`, **not** `localhost`, from Windows)
- pgvector integration test (opt-in): `TEST_POSTGRES_URL=postgresql+asyncpg://ai_power:<password>@192.168.29.100:5432/ai_power_test .venv/Scripts/python.exe -m pytest tests/test_postgres_vector.py`
- SQL inside the container on Windows: `printf 'SELECT 1;\n' | docker exec -i <postgres-container> psql -U ai_power -d postgres` (`docker exec ... -c "SQL with spaces"` gets split on Windows)

## Architecture

- **Layering**: `app/routers/*` (HTTP) → `app/deps.py` (auth + provider registry) → `app/services/*` (access, parsing, chunking, storage, ingestion) → `app/models.py` / `app/schemas.py` / `app/security.py`. `app/providers/` owns LLM + embedding boundaries; `app/vector.py` owns the pgvector/JSON type.
- **Auth flow**: argon2id hashing; `POST /auth/login` returns an HS256 JWT (`sub` = user UUID, 24h). Every protected route resolves `User` via `HTTPBearer`; cross-user resource access returns **404, not 403**.
- **Provider boundary**: `LLMProvider` (`list_models`, `stream_chat`) + `EmbeddingProvider` (`embed`). `OpenAICompatProvider` / `OpenAICompatEmbeddingProvider` implement DeepSeek / llama.cpp / vLLM. Streaming chat sends `stream_options.include_usage=true`; usage stays nullable.
- **Chat flow**: `POST /conversations/{id}/messages` persists user + assistant (`streaming`) messages, then streams SSE `meta → delta* → usage → done` (or terminal `error`). The generator finalizes the assistant message in a fresh `SessionLocal` session.
- **Ingestion flow**: `POST /knowledge-bases/{kb_id}/documents` validates ownership + extension, writes a UUID-named file under `UPLOAD_DIR`, inserts `Document(uploaded)` + `IngestionJob(queued)`, and schedules `ingest_document` via `BackgroundTasks`. The service moves `uploaded → parsing → embedding → ready`; failures set `failed + error_code` and mark the job failed. Duplicate `(user, kb, content_hash)` returns the existing document with `duplicate=true`.
- **Vector storage**: `EmbeddingVector` maps to pgvector `vector(1024)` on Postgres and JSON on SQLite. `init_db()` creates the `vector` extension on Postgres. Distance queries use `EmbeddingVector` comparators (`l2_distance`, `cosine_distance`).
- **Persistence**: dev/tests use SQLite (`aiosqlite`, `NullPool`); production P0 targets Postgres + pgvector via `DATABASE_URL`. Tables are created by `init_db()`; **Alembic has not been introduced yet**.
- **Tests**: `tests/conftest.py` sets DB/JWT/upload/chunk env before importing the app, recreates the schema per test, and drives the ASGI app with `httpx.ASGITransport`. Conversation tests override `get_registry`; ingestion tests override `build_parser`/`build_embedder` via the `fake_ingestion` fixture. Coverage requires `concurrency = ["greenlet", "thread"]`.
- **External model services**: local Qwen `http://192.168.29.100:8083/v1` (llama.cpp), bge-m3 `http://192.168.29.100:8000/v1` (vLLM, 1024 dims), DeepSeek `https://api.deepseek.com`.

## Conventions

- Tests first: write the failing test, run it, then implement. Keep RED/GREEN evidence in `docs/tdd/`.
- Any new user-owned resource must filter by `user_id` and return 404 on cross-user access; add an isolation test with two users.
- Ingestion must be idempotent per `(user_id, kb_id, content_hash)`; every failure sets a typed `error_code` and `IngestionJob.status = failed`.
- Uploads: allowlist extensions (.pdf/.md/.txt), never trust the client filename or content type for paths; store as UUID + suffix under `UPLOAD_DIR`.
- SSE event contract is fixed: `meta`, `delta`, `usage`, `done`, `error`; `error` is terminal.
- Provider/embedding code must not import vendor SDKs outside `app/providers/`; keys come from settings/env only.
- Never log `Authorization`, provider API keys, or full document text.
- Windows-specific: use `.venv/Scripts/python.exe`; Docker host is `192.168.29.100`, not `localhost`; pass SQL to `psql` via stdin.