"""PersonalAI ports: the stable interfaces (seams) that adapters implement.

These Protocols are the contract between the core and concrete adapters. Adapters depend
inward on this package only and never import each other (ADR-0001).
"""

from personalai_contracts.ports.agent import (
    AgentContext,
    AgentNode,
    AgentRole,
    AgentState,
)
from personalai_contracts.ports.identity import (
    AuthKind,
    AuthResult,
    IdentityProvider,
    SecurityContext,
    Session,
    SessionStore,
)
from personalai_contracts.ports.modality import (
    MediaRef,
    ModalityHandler,
    ModalityKind,
    ParsedContent,
)
from personalai_contracts.ports.model_provider import (
    ChatMessage,
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
    ModelDescriptor,
    ModelProvider,
    Role,
    ToolCallRequest,
    ToolSpec,
)
from personalai_contracts.ports.reranker import Reranker
from personalai_contracts.ports.retriever import (
    SOURCE_KIND_GRAPH,
    SOURCE_KIND_MEMORY,
    SOURCE_KIND_VECTOR,
    Citation,
    Evidence,
    RetrievalQuery,
    RetrievalSource,
    RetrievedItem,
    Retriever,
)
from personalai_contracts.ports.storage import (
    GLOBAL_SCOPE,
    GraphStore,
    MemoryItem,
    MemoryKind,
    MemoryStore,
    ObjectStore,
    Repository,
    Scope,
    VectorMatch,
    VectorRecord,
    VectorRepository,
)
from personalai_contracts.ports.tool import (
    ToolCall,
    ToolExecutor,
    ToolHandler,
    ToolResult,
)
from personalai_contracts.ports.transcribe import (
    Transcriber,
    Transcription,
)

__all__ = [
    # agent
    "AgentContext",
    "AgentNode",
    "AgentRole",
    "AgentState",
    # identity
    "AuthKind",
    "AuthResult",
    "IdentityProvider",
    "SecurityContext",
    "Session",
    "SessionStore",
    # modality
    "MediaRef",
    "ModalityHandler",
    "ModalityKind",
    "ParsedContent",
    # model provider
    "ChatMessage",
    "EmbeddingResult",
    "GenerationChunk",
    "GenerationRequest",
    "GenerationResult",
    "ModelCapabilities",
    "ModelDescriptor",
    "ModelProvider",
    "Role",
    "ToolCallRequest",
    "ToolSpec",
    # reranker
    "Reranker",
    # retriever
    "SOURCE_KIND_GRAPH",
    "SOURCE_KIND_MEMORY",
    "SOURCE_KIND_VECTOR",
    "Citation",
    "Evidence",
    "RetrievalQuery",
    "RetrievalSource",
    "RetrievedItem",
    "Retriever",
    # storage
    "GLOBAL_SCOPE",
    "GraphStore",
    "MemoryItem",
    "MemoryKind",
    "MemoryStore",
    "ObjectStore",
    "Repository",
    "Scope",
    "VectorMatch",
    "VectorRecord",
    "VectorRepository",
    # tool
    "ToolCall",
    "ToolExecutor",
    "ToolHandler",
    "ToolResult",
    # transcribe
    "Transcriber",
    "Transcription",
]
