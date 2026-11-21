from app.db import SessionLocal
from app.models import Chunk, ChunkEmbedding, Document, KnowledgeBase, User, Workspace


async def _seed(session, keyword_embedder):
    user = User(email="eval@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="eval", plan="free", is_personal=False)
    session.add(workspace)
    await session.flush()
    kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name="eval")
    session.add(kb)
    await session.flush()

    documents = []
    for index, (filename, text, position) in enumerate(
        [("refund.txt", "退款流程", 0), ("invoice.txt", "发票申请", 1)]
    ):
        document = Document(
            workspace_id=workspace.id,
            kb_id=kb.id,
            user_id=user.id,
            filename=filename,
            mime="text/plain",
            size_bytes=1,
            content_hash=f"hash-{index}",
            storage_path=filename,
            status="ready",
        )
        session.add(document)
        await session.flush()
        chunk = Chunk(
            workspace_id=workspace.id,
            document_id=document.id,
            user_id=user.id,
            kb_id=kb.id,
            page_no=1,
            chunk_index=0,
            text=text,
        )
        session.add(chunk)
        await session.flush()
        vector = [0.0] * 1024
        vector[position] = 1.0
        session.add(ChunkEmbedding(chunk_id=chunk.id, embedding=vector))
        documents.append(document)
    keyword_embedder.mapping = {"退款": 0, "发票": 1}
    await session.commit()
    return user, kb, documents


async def test_recall_counts_questions_with_a_relevant_hit(keyword_embedder):
    from app.services.evaluation import EvalQuestion, evaluate_recall

    async with SessionLocal() as session:
        user, kb, documents = await _seed(session, keyword_embedder)
        refund, _invoice = documents
        questions = [
            EvalQuestion("退款要多久？", frozenset({refund.id})),
            EvalQuestion("发票怎么开？", frozenset({refund.id})),
        ]

        report = await evaluate_recall(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            questions=questions,
            top_k=1,
            embedder=keyword_embedder,
        )

        assert report.total == 2
        assert report.hits == 1
        assert report.recall == 0.5
        assert report.missed == ("发票怎么开？",)


async def test_recall_is_zero_for_empty_dataset(keyword_embedder):
    from app.services.evaluation import evaluate_recall

    async with SessionLocal() as session:
        user, kb, _documents = await _seed(session, keyword_embedder)

        report = await evaluate_recall(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            questions=[],
            top_k=1,
            embedder=keyword_embedder,
        )

        assert report.total == 0
        assert report.recall == 0.0
        assert report.missed == ()
