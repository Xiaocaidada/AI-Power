from uuid import uuid4

from app.services.ingestion import IngestionOutcome


class FakePool:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))


async def test_worker_retries_failed_ingestion_with_backoff(monkeypatch):
    import app.worker as worker

    document_id = uuid4()
    scheduled: list[object] = []
    dead: list[object] = []
    pool = FakePool()

    async def fake_ingest(_document_id):
        return IngestionOutcome(status="failed", error_code="parse_failed", attempts=1)

    async def fake_schedule(_document_id):
        scheduled.append(_document_id)

    async def fake_dead(_document_id):
        dead.append(_document_id)

    monkeypatch.setattr(worker, "ingest_document", fake_ingest)
    monkeypatch.setattr(worker, "schedule_retry", fake_schedule)
    monkeypatch.setattr(worker, "mark_job_dead", fake_dead)

    await worker.ingest_document_job({"redis": pool}, str(document_id))

    assert scheduled == [document_id]
    assert dead == []
    name, args, kwargs = pool.jobs[0]
    assert name == "ingest_document_job"
    assert args == (str(document_id),)
    assert kwargs["_defer"] == 2
    assert kwargs["_job_id"].endswith(":retry:1")


async def test_worker_marks_dead_after_max_attempts(monkeypatch):
    import app.worker as worker

    document_id = uuid4()
    scheduled: list[object] = []
    dead: list[object] = []
    pool = FakePool()

    async def fake_ingest(_document_id):
        return IngestionOutcome(status="failed", error_code="parse_failed", attempts=3)

    async def fake_schedule(_document_id):
        scheduled.append(_document_id)

    async def fake_dead(_document_id):
        dead.append(_document_id)

    monkeypatch.setattr(worker, "ingest_document", fake_ingest)
    monkeypatch.setattr(worker, "schedule_retry", fake_schedule)
    monkeypatch.setattr(worker, "mark_job_dead", fake_dead)

    await worker.ingest_document_job({"redis": pool}, str(document_id))

    assert scheduled == []
    assert dead == [document_id]
    assert pool.jobs == []


async def test_worker_does_nothing_on_success(monkeypatch):
    import app.worker as worker

    scheduled: list[object] = []
    dead: list[object] = []
    pool = FakePool()

    async def fake_ingest(_document_id):
        return IngestionOutcome(status="ready", attempts=1)

    async def fake_schedule(_document_id):
        scheduled.append(_document_id)

    async def fake_dead(_document_id):
        dead.append(_document_id)

    monkeypatch.setattr(worker, "ingest_document", fake_ingest)
    monkeypatch.setattr(worker, "schedule_retry", fake_schedule)
    monkeypatch.setattr(worker, "mark_job_dead", fake_dead)

    await worker.ingest_document_job({"redis": pool}, str(uuid4()))

    assert scheduled == []
    assert dead == []
    assert pool.jobs == []
