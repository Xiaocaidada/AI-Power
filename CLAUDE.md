# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

P0 complete. **S1**: auth + per-user isolation. **S2**: provider abstraction + SSE chat. **S3**: document upload + async ingestion (PDF/MD/TXT → chunks → bge-m3 → pgvector). **S4**: retrieval + citations + RAG chat (HNSW, `citation` SSE). **Eval**: 20-document / 50-question Chinese set with a measured Recall@5 baseline (real bge-m3). **P1-S1 complete**: Alembic migrations, refresh tokens (30m access / 7d refresh, rotation + revocation), login rate limiting, `/readyz`, Dockerfile + compose `api` + CI. **P1-S2 complete**: Arq durable ingestion queue (leases, retries, dead letters), manual document retry, file deletion + orphan cleanup, compose `worker`. **P1-S3 complete**: append-only `usage_events`, `GET /usage/summary`, and persisted `message_citations` replayed on conversation history. **P1-S4 complete**: API keys (`X-API-Key`) with `chat:write`/`kb:read` scopes, one-time plaintext, SHA-256 storage, revocation, and throttled `last_used_at`. **P1 complete**: auth + refresh, chat/SSE + citations, knowledge base + durable ingestion, usage metering, API keys, full frontend (chat, KB, usage, keys, profile, zh/en), and LAN Docker deployment with nginx, structured logs, daily backups, and a 20-concurrency load test (20/20, TTFT P95 46.9s on local Qwen). **P2-S2 complete**: model catalog (`/models`, `/models/compare`), `auto` routing with pre-first-token fallback, and a Redis circuit breaker. Next: P2-S3 (workspace + key quotas). See `docs/plan/p2-plan.md`; code per slice needs approval.

## Documents

- [PRODUCT-BRIEF.md](./PRODUCT-BRIEF.md) — 产品诊断、路线图 P0–P3、反目标与成功指标。
- [docs/product/CAPABILITY.md](./docs/product/CAPABILITY.md) — P0 能力契约：API、状态机、数据模型、安全约束与开放问题。
- [docs/adr/0001-p0-stack.md](./docs/adr/0001-p0-stack.md) — 技术栈与模型接入决策。
- [docs/adr/0002-ingestion.md](./docs/adr/0002-ingestion.md) — 入库执行器、pgvector、分块、幂等与失败码。
- [docs/adr/0003-retrieval.md](./docs/adr/0003-retrieval.md) — 检索参数、L2/HNSW、引用真实性、注入防护与失败语义。
- [docs/tdd/p0-s1-auth.md](./docs/tdd/p0-s1-auth.md) — S1 的 RED/GREEN 证据。
- [docs/tdd/p0-s2-provider-sse.md](./docs/tdd/p0-s2-provider-sse.md) — S2 的 SSE 契约与真实模型冒烟。
- [docs/tdd/p0-s3-ingestion.md](./docs/tdd/p0-s3-ingestion.md) — S3 的入库状态机、真实 bge-m3 与 pgvector 证据。
- [docs/tdd/p0-s4-retrieval.md](./docs/tdd/p0-s4-retrieval.md) — S4 的检索/引用证据、真实 bge-m3 排序与 HNSW 集成。
- [docs/eval/retrieval-baseline.md](./docs/eval/retrieval-baseline.md) — 20 文档 / 50 题中文评测集与 Recall@1/3/5 基线。
- [docs/plan/p1-plan.md](./docs/plan/p1-plan.md) — P1 规划：基础设施、队列、用量、API Key、前端与部署切片。
- [docs/plan/p1-s5-frontend-ui.md](./docs/plan/p1-s5-frontend-ui.md) — P1-S5 前端 UI 规划：设计令牌、页面规格、SSE 客户端、i18n 与 S5-pre 缺口。
- [docs/plan/p2-plan.md](./docs/plan/p2-plan.md) — P2 规划：多租户、模型广场与路由降级、配额、trace；含待确认决策。
- [docs/adr/0004-auth-sessions.md](./docs/adr/0004-auth-sessions.md) — refresh token、轮换/吊销与登录限流决策。
- [docs/tdd/p1-s1-infra.md](./docs/tdd/p1-s1-infra.md) — P1-S1 的 RED/GREEN 证据、Alembic 与健康检查。
- [docs/adr/0005-ingestion-queue.md](./docs/adr/0005-ingestion-queue.md) — Arq 队列、租约/重试/死信与文件生命周期。
- [docs/tdd/p1-s2-queue.md](./docs/tdd/p1-s2-queue.md) — P1-S2 的 RED/GREEN 证据与队列端到端验证。
- [docs/adr/0006-usage-metering.md](./docs/adr/0006-usage-metering.md) — 只追加用量事件、聚合 API 与引用持久化。
- [docs/tdd/p1-s3-usage.md](./docs/tdd/p1-s3-usage.md) — P1-S3 的 RED/GREEN、Postgres 回填与容器端到端证据。
- [docs/adr/0007-api-keys.md](./docs/adr/0007-api-keys.md) — API Key 格式/哈希、scope 与路由权限映射。
- [docs/tdd/p1-s4-api-keys.md](./docs/tdd/p1-s4-api-keys.md) — P1-S4 的 RED/GREEN 与容器端到端证据。
- [docs/tdd/p1-s5-pre-frontend-contract.md](./docs/tdd/p1-s5-pre-frontend-contract.md) — S5-pre 的 CORS 与文档列表接口证据。
- [docs/tdd/p1-s5a-frontend.md](./docs/tdd/p1-s5a-frontend.md) — S5a 前端骨架、认证与对话证据（含真实浏览器验证）。
- [docs/tdd/p1-s5b-knowledge.md](./docs/tdd/p1-s5b-knowledge.md) — S5b 知识库与文档管理证据。
- [docs/tdd/p1-s5c-console.md](./docs/tdd/p1-s5c-console.md) — S5c 用量、API Key 与个人资料证据。
- [docs/adr/0008-deployment.md](./docs/adr/0008-deployment.md) — compose 全栈、nginx、日志、连接池、备份与压测决策。
- [docs/tdd/p1-s6-deploy.md](./docs/tdd/p1-s6-deploy.md) — P1-S6 的 RED/GREEN、全栈验证与 20 并发压测证据。
- [docs/tdd/p2-s1-workspaces.md](./docs/tdd/p2-s1-workspaces.md) — P2-S1 的 workspace 迁移与跨租户隔离证据。
- [docs/tdd/p2-s2-routing.md](./docs/tdd/p2-s2-routing.md) — P2-S2 的模型目录、`auto` 降级与熔断证据。

## Commands

All Python commands use the project venv. On Windows that is `.venv/Scripts/python.exe`.

- Setup: `uv venv --python 3.13 .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`
- Run tests: `.venv/Scripts/python.exe -m pytest`
- Run one test: `.venv/Scripts/python.exe -m pytest tests/test_documents.py::test_upload_ingests_and_marks_ready`
- Coverage: `.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing`
- Lint: `.venv/Scripts/python.exe -m ruff check .`
- Format: `.venv/Scripts/python.exe -m ruff format .`
- Run app: `.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000`
- Migrations: `.venv/Scripts/python.exe -m alembic upgrade head` (new revision: `... revision --autogenerate -m "..."`; requires a DB whose schema matches the models)
- Docker API + worker: `docker compose up -d api worker` (API runs `alembic upgrade head` before uvicorn; host port **8002**, because the VM's 8000/8001 are occupied by vLLM)
- Docker full stack: `docker compose up -d --build` (adds `web` on **8080** and `backup`; web serves the built SPA and proxies `/api` to `api:8000`)
- Logs: `docker compose logs -f api worker web`
- Manual backup now: `docker compose exec -e RUN_ONCE=1 backup /bin/sh /usr/local/bin/backup_postgres.sh`
- Load test: `.venv/Scripts/python.exe scripts/loadtest.py --base-url http://192.168.29.100:8080/api --concurrency 20`
- Docker build uses the Tsinghua PyPI mirror by default; override with `docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ api`
- Local worker (needs Redis): `.venv/Scripts/python.exe -m arq app.worker.WorkerSettings`
- Postgres + Redis: `docker compose up -d postgres redis` (Docker runs in WSL; use host `192.168.29.100`, **not** `localhost`, from Windows)
- pgvector integration test (opt-in): `TEST_POSTGRES_URL=postgresql+asyncpg://ai_power:<password>@192.168.29.100:5432/ai_power_test .venv/Scripts/python.exe -m pytest tests/test_postgres_vector.py`
- SQL inside the container on Windows: `printf 'SELECT 1;\n' | docker exec -i <postgres-container> psql -U ai_power -d postgres` (`docker exec ... -c "SQL with spaces"` gets split on Windows)
- Seed retrieval eval KB (deterministic IDs, real ingestion + bge-m3, writes `eval/questions.jsonl`): `.venv/Scripts/python.exe scripts/seed_eval.py`
- Retrieval eval: `.venv/Scripts/python.exe scripts/eval_retrieval.py --dataset eval/questions.jsonl --workspace-id <uuid> --kb-id <uuid> --top-k 5` (seed script prints both IDs)
- Seed model catalog: `docker compose cp scripts/seed_models.py api:/tmp/seed_models.py && docker compose exec -T api python /tmp/seed_models.py`
- Frontend install: `cd web && npm install`
- Frontend dev: `cd web && npm run dev` (port 5173; `/api` proxies to `VITE_PROXY_TARGET`, default `http://192.168.29.100:8002`). If `/api/*` returns SPA HTML, a stale Vite process still owns port 5173 — kill it and restart.
- Frontend tests: `cd web && npm test`
- Frontend build: `cd web && npm run build` (runs `tsc --noEmit` first)
- Frontend typecheck: `cd web && npm run typecheck`

## Architecture

- **Layering**: `app/routers/*` (HTTP) → `app/deps.py` (auth + provider registry) → `app/services/*` (access, parsing, chunking, storage, ingestion, retrieval, rag, evaluation) → `app/models.py` / `app/schemas.py` / `app/security.py`. `app/providers/` owns LLM + embedding boundaries; `app/vector.py` owns the pgvector/JSON type.
- **Auth flow**: argon2id hashing; `POST /auth/login` returns a 30-minute HS256 access JWT (`sub` = user UUID, plus `jti`) and a 7-day refresh token. `POST /auth/refresh` rotates the refresh token once (old one is revoked and reused tokens are rejected); `POST /auth/logout` revokes it. Refresh tokens are stored as SHA-256 hashes in `refresh_tokens`. Login is rate limited per client IP via Redis (10/min, fail-open with a warning). Every protected route resolves `User` via `HTTPBearer`; cross-user resource access returns **404, not 403**.
- **Tenancy**: every user gets a personal `workspace` at registration. Resources (`knowledge_bases`, `conversations`, `documents`, `chunks`, `ingestion_jobs`, `usage_events`, `api_keys`) carry `workspace_id`; `AuthContext` = user + workspace + role + scopes. JWT requests pick a workspace via `X-Workspace-Id` (defaults to personal); API keys are bound to their workspace and reject a conflicting header. Cross-workspace access returns 404. Owners invite/remove members by email; members see workspace resources.
- **API keys**: `X-API-Key` (format `ap_<8hex>_<secret>`) is accepted by `get_auth_context`; only SHA-256 hashes are stored in `api_keys`, plaintext is returned once at creation. JWT = full permissions; keys are limited by `chat:write` / `kb:read` via `require_scope`. Key management, uploads, deletes, archive, and `/usage` stay JWT-only. `last_used_at` is written at most once per 60s. Never log key values.
- **Frontend contract**: `CORSMiddleware` allows origins from `CORS_ORIGINS` (default Vite `5173` + LAN `8080`), permits `Authorization`/`Content-Type`/`X-API-Key`, and exposes `Retry-After`. `GET /knowledge-bases/{kb_id}/documents` lists non-deleted documents newest-first (UUIDv7 tiebreak) behind `kb:read`; cross-user returns 404.
- **Frontend (`web/`)**: Vite + React 18 + TypeScript, React Router, TanStack Query (server state), Zustand (auth/UI only), Tailwind tokens. `/api` is proxied in dev. Access token lives in memory; refresh token in `localStorage` with single-flight rotation and one retry on 401. Chat uses `fetch` + `ReadableStream` (not EventSource), parses `meta/citation/delta/usage/done/error`, renders plain text while streaming and Markdown after `done`, and replays persisted citations on history load. zh/en dictionaries are typed and key-parity tested. Routes: `/login`, `/chat`, `/chat/:id`, `/knowledge`, `/knowledge/:id`, `/usage`, `/settings/api-keys`, `/settings/profile`. Usage loads Recharts lazily. Uploads use XHR for progress; document status polling runs every 2s only while a document is `uploaded/parsing/embedding`. API keys are shown in full once (non-dismissible dialog) and never persisted client-side.
- **Model catalog & routing**: `model_catalog` holds provider/model metadata (`priority`, `enabled`, prices, tags). `GET /models` merges it with circuit health; `GET /models/compare?ids=` compares up to 5. Conversations can use `provider_id="auto"`, which resolves candidates by priority, skips providers with ≥3 Redis failures in 60s, and falls back to the next provider only before the first token. Mid-stream failures emit an SSE `error` and are not retried. Messages store the actual provider/model used.
- **Provider boundary**: `LLMProvider` (`list_models`, `stream_chat`) + `EmbeddingProvider` (`embed`). `OpenAICompatProvider` / `OpenAICompatEmbeddingProvider` implement DeepSeek / llama.cpp / vLLM. Streaming chat sends `stream_options.include_usage=true`; usage stays nullable.
- **Chat flow**: `POST /conversations/{id}/messages` persists user + assistant (`streaming`) messages, then streams SSE `meta → delta* → usage → done` (or terminal `error`). When the conversation has `kb_id`, retrieval runs **before** messages are persisted and the stream becomes `meta → citation* → delta* → usage → done`; a retrieval provider failure returns HTTP 502 `retrieval_failed` and persists nothing. The generator finalizes the assistant message in a fresh `SessionLocal` session and writes one append-only `usage_events` row (even when usage is null) plus any `message_citations`. `GET /conversations/{id}` replays persisted citations.
- **Usage API**: `GET /usage/summary?from&to&group_by=day|provider|model` aggregates only the current user's events in Python (P1 volumes) and returns requests/prompt/completion/total tokens per bucket.
- **Ingestion flow**: `POST /knowledge-bases/{kb_id}/documents` validates ownership + extension, writes a UUID-named file under `UPLOAD_DIR`, inserts `Document(uploaded)` + `IngestionJob(queued)`, and enqueues `ingest_document_job` on Arq (job id `ingest:<document_id>`). The worker runs `uploaded → parsing → embedding → ready`; failures return an `IngestionOutcome`, retry with `2**attempts` backoff (max `INGESTION_MAX_ATTEMPTS`), then mark the job `dead`. Each run sets `started_at`/`lease_expires_at`; a per-minute cron requeues `running` jobs with expired leases. `POST /documents/{id}/retry` resets a failed document and enqueues it again. Queue failure marks the document `failed + queue_unavailable` and returns 503. Duplicate `(user, kb, content_hash)` returns the existing document with `duplicate=true`.
- **Retrieval/RAG flow**: `retrieve_chunks` embeds the query once, filters `chunk.user_id`, `chunk.kb_id`, `document.status='ready'`, `document.deleted_at IS NULL`, and orders by L2. Postgres uses SQL `<->`; SQLite scores candidates in Python (test-only path). `fit_context` greedily keeps ranked chunks within `RETRIEVAL_MAX_CONTEXT_CHARS`; citations are built **from the chunks actually placed in the prompt** (never parsed from model text); `build_rag_messages` prepends a system prompt that declares `<reference_material>` untrusted data.
- **Vector storage**: `EmbeddingVector` maps to pgvector `vector(1024)` on Postgres and JSON on SQLite. `init_db()` creates the `vector` extension and the idempotent HNSW index (`ix_chunk_embeddings_embedding_hnsw`, `vector_l2_ops`) on Postgres. Distance queries use `EmbeddingVector` comparators (`l2_distance`, `cosine_distance`).
- **Persistence**: dev/tests use SQLite (`aiosqlite`, `NullPool`); production targets Postgres + pgvector via `DATABASE_URL`. Schema changes go through Alembic (`alembic/versions/`); `init_db()` still creates tables for tests and local dev. The Docker API command runs `alembic upgrade head` before uvicorn.
- **Deployment**: compose runs `postgres`, `redis`, `api`, `worker`, `web`, `backup`. nginx serves `web/dist`, falls back to `index.html`, and proxies `/api/` to `api:8000` with proxy buffering off for SSE; host ports are 8080 (web) and 8002 (api). `backup` runs `pg_dump -Fc` daily into the `backups` volume and keeps 7 days. API/worker use `LOG_FORMAT=json`; every request carries `X-Request-ID` and logs `method/path/status/duration_ms/user_id`. Streaming endpoints close their request-scoped DB session before returning, and the Postgres pool is 10+20 with `PROVIDER_TIMEOUT_SECONDS=180` in compose to survive 20 concurrent local-model streams.
- **Health**: `/healthz` is liveness; `/readyz` checks `SELECT 1` and Redis `PING` and returns 503 with per-check status when a dependency is down.
- **File lifecycle**: deleting a document also removes its stored file; a daily worker cron deletes unreferenced files older than 24h. API and worker share the `uploads` compose volume.
- **Tests**: `tests/conftest.py` sets DB/JWT/upload/chunk env before importing the app, recreates the schema per test, and drives the ASGI app with `httpx.ASGITransport`. Conversation tests override `get_registry`; ingestion tests override `build_parser`/`build_embedder` via the `fake_ingestion` fixture. Coverage requires `concurrency = ["greenlet", "thread"]`.
- **External model services**: local Qwen `http://192.168.29.100:8083/v1` (llama.cpp), bge-m3 `http://192.168.29.100:8000/v1` (vLLM, 1024 dims), DeepSeek `https://api.deepseek.com`.

## Conventions

- Tests first: write the failing test, run it, then implement. Keep RED/GREEN evidence in `docs/tdd/`.
- Any new user-owned resource must filter by `user_id` and return 404 on cross-user access; add an isolation test with two users.
- Ingestion must be idempotent per `(user_id, kb_id, content_hash)`; every failure sets a typed `error_code` and `IngestionJob.status = failed`.
- Uploads: allowlist extensions (.pdf/.md/.txt), never trust the client filename or content type for paths; store as UUID + suffix under `UPLOAD_DIR`.
- SSE event contract is fixed: `meta`, `citation`, `delta`, `usage`, `done`, `error`; `error` is terminal, `citation` only appears for retrieved chunks actually used in the prompt.
- Never build citations by parsing model output; build them from `RetrievedChunk` IDs after `fit_context`.
- `usage_events` is append-only: never update or delete rows from business code; aggregate by query.
- Provider/embedding code must not import vendor SDKs outside `app/providers/`; keys come from settings/env only.
- Never log `Authorization`, provider API keys, or full document text.
- Windows-specific: use `.venv/Scripts/python.exe`; Docker host is `192.168.29.100`, not `localhost`; pass SQL to `psql` via stdin.