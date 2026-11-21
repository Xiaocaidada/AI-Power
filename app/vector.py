from typing import Any

from sqlalchemy import JSON, Float, literal
from sqlalchemy.types import TypeDecorator


class EmbeddingComparator(TypeDecorator.Comparator):
    def l2_distance(self, other: Any):
        return self.expr.op("<->", return_type=Float)(literal(other, type_=self.expr.type))

    def cosine_distance(self, other: Any):
        return self.expr.op("<=>", return_type=Float)(literal(other, type_=self.expr.type))


class EmbeddingVector(TypeDecorator):
    """pgvector on Postgres, JSON on SQLite (tests)."""

    impl = JSON
    cache_ok = True
    comparator_factory = EmbeddingComparator

    def __init__(self, dimensions: int = 1024, **kwargs: Any) -> None:
        self.dimensions = dimensions
        super().__init__(**kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(item) for item in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(item) for item in value]
