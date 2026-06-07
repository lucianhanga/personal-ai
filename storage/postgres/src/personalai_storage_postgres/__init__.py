"""PostgreSQL + pgvector storage adapters for PersonalAI."""

from personalai_storage_postgres.db import apply_migrations, create_pool
from personalai_storage_postgres.document_store import Document, PgDocumentStore
from personalai_storage_postgres.vector_repo import VECTOR_DIM, PgVectorRepository

__all__ = [
    "VECTOR_DIM",
    "Document",
    "PgDocumentStore",
    "PgVectorRepository",
    "apply_migrations",
    "create_pool",
]
