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
from personalai_contracts.ports.retriever import (
    Citation,
    RetrievalQuery,
    RetrievedItem,
    Retriever,
)
from personalai_contracts.ports.storage import (
    GraphStore,
    MemoryItem,
    MemoryKind,
    MemoryStore,
    ObjectStore,
    Repository,
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

__all__ = [
    # agent
    "AgentContext",
    "AgentNode",
    "AgentRole",
    "AgentState",
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
    # retriever
    "Citation",
    "RetrievalQuery",
    "RetrievedItem",
    "Retriever",
    # storage
    "GraphStore",
    "MemoryItem",
    "MemoryKind",
    "MemoryStore",
    "ObjectStore",
    "Repository",
    "VectorMatch",
    "VectorRecord",
    "VectorRepository",
    # tool
    "ToolCall",
    "ToolExecutor",
    "ToolHandler",
    "ToolResult",
]
