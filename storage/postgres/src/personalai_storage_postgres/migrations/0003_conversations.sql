-- Conversation history (M3-4). Messages cascade-delete with their conversation.
CREATE TABLE IF NOT EXISTS conversations (
    id text PRIMARY KEY,
    title text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx ON messages (conversation_id, id);
