import time


class VectorStoreConversationsMixin:

    def add_conversation(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        character_name: str = "",
    ) -> None:
        embedding = self.embedding_model.encode([user_message])[0]
        self.client.insert(
            collection_name=self.conversation_collection_name,
            data=[
                {
                    "vector": embedding,
                    "session_id": session_id,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                    "character_name": (character_name or "").strip(),
                    "timestamp": int(time.time()),
                }
            ],
        )

    def delete_conversation(self, session_id: str) -> None:
        escaped_session_id = self._escape_filter_value(session_id)
        self.client.delete(
            collection_name=self.conversation_collection_name,
            filter=f"session_id == '{escaped_session_id }'",
        )
