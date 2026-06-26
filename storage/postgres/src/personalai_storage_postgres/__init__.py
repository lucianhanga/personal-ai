"""PostgreSQL + pgvector storage adapters for PersonalAI."""

from personalai_storage_postgres.agent_config_store import PgAgentConfigStore
from personalai_storage_postgres.conversation_store import (
    Conversation,
    Message,
    PgConversationStore,
)
from personalai_storage_postgres.db import apply_migrations, create_pool
from personalai_storage_postgres.document_store import Document, PgDocumentStore
from personalai_storage_postgres.folder_store import (
    FileStatus,
    FolderExistsError,
    FolderFile,
    FolderSource,
    PgFolderStore,
)
from personalai_storage_postgres.memory_store import PgMemoryStore
from personalai_storage_postgres.session_store import PgSessionStore
from personalai_storage_postgres.settings_store import PgSettingsStore
from personalai_storage_postgres.tenant_checkpoint_saver import TenantCheckpointSaver
from personalai_storage_postgres.tenant_db import TenantDb
from personalai_storage_postgres.tenant_store import (
    DEFAULT_TENANT_ID,
    PgTenantStore,
    Subject,
    Tenant,
)
from personalai_storage_postgres.vector_repo import VECTOR_DIM, PgVectorRepository

__all__ = [
    "DEFAULT_TENANT_ID",
    "VECTOR_DIM",
    "Conversation",
    "Document",
    "FolderExistsError",
    "FileStatus",
    "FolderFile",
    "FolderSource",
    "Message",
    "PgAgentConfigStore",
    "PgConversationStore",
    "PgDocumentStore",
    "PgFolderStore",
    "PgMemoryStore",
    "PgSessionStore",
    "PgSettingsStore",
    "PgTenantStore",
    "PgVectorRepository",
    "Subject",
    "Tenant",
    "TenantCheckpointSaver",
    "TenantDb",
    "apply_migrations",
    "create_pool",
]
