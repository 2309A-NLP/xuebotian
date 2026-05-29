from app.services.data_loader import clean_name, normalize_knowledge_scope


class VectorStoreDocumentsMixin:

    def _build_search_text(self, doc: dict) -> str:

        parts = [f"character: {(doc .get ('name')or '').strip ()}"]

        source_file = (doc.get("source_file") or "").strip()
        if source_file:
            parts.append(f"source: {source_file }")

        source_title = (doc.get("source_title") or "").strip()
        if source_title:
            parts.append(f"title: {source_title }")

        original_name = (doc.get("original_name") or "").strip()
        if original_name:
            parts.append(f"original: {original_name }")

        parts.append(f"content: {(doc .get ('message')or '').strip ()}")

        return "\n".join(part for part in parts if part.strip())

    def _normalize_match_text(self, text: str) -> str:
        import re

        return re.sub(r"\s+", "", (text or "").strip().lower())

    def _build_document_key(self, doc: dict) -> str:
        return (
            f"{self ._build_parent_id (doc )}||{doc .get ('message','')}||"
            f"{int (doc .get ('chunk_index',0 )or 0 )}||{self ._normalize_access_key (doc )}"
        )

    def hydrate_documents(self, documents):
        self.documents = []

    def get_document_count(self) -> int:
        if not self.client.has_collection(self.collection_name):
            return 0
        rows = self._query_all_by_id(
            collection_name=self.collection_name,
            output_fields=[],
            limit=1000000,
        )
        return len(rows)

    def get_character_previews(self, max_length: int = 160):
        previews = {}
        for doc in sorted(
            self.load_documents_from_milvus(limit=100000),
            key=lambda item: (
                item.get("name", ""),
                item.get("source_file", ""),
                int(item.get("chunk_index", 0) or 0),
            ),
        ):
            name = doc.get("name") or ""
            preview_text = (doc.get("message") or "").strip()
            if not name or name in previews or not preview_text:
                continue
            previews[name] = preview_text[:max_length]
        return previews

    def _encode_documents(self, documents):
        texts = [self._build_search_text(doc) for doc in documents]
        unique_texts = list(dict.fromkeys(texts))
        encoded_by_text = {}
        batch_size = self.embedding_batch_size
        for start in range(0, len(unique_texts), batch_size):
            batch = unique_texts[start : start + batch_size]
            batch_embeddings = self.embedding_model.encode(
                batch,
                batch_size=self.embedding_batch_size,
            )
            for index, text in enumerate(batch):
                encoded_by_text[text] = batch_embeddings[index]
        return [encoded_by_text[text] for text in texts]

    def _insert_document_batches(self, documents, batch_size=None) -> int:
        inserted = 0
        total = len(documents)
        resolved_batch_size = max(1, batch_size or self.insert_batch_size)
        for start in range(0, total, resolved_batch_size):
            batch = documents[start : start + resolved_batch_size]
            embeddings = self._encode_documents(batch)
            data = self._serialize_documents(batch, embeddings)
            self.client.insert(collection_name=self.collection_name, data=data)
            inserted += len(batch)
            print(
                f"知识写入进度: {inserted }/{total } "
                f"(向量批大小={self .embedding_batch_size }, 写入批大小={resolved_batch_size })"
            )
        return inserted

    def _serialize_documents(self, documents, embeddings):
        return [
            {
                "vector": embeddings[index],
                "search_text": self._build_search_text(doc),
                "name": doc["name"],
                "message": doc["message"],
                "source_file": doc.get("source_file", ""),
                "parent_id": self._build_parent_id(doc),
                "source_title": (doc.get("source_title") or "")[:255],
                "chunk_index": int(doc.get("chunk_index", 0) or 0),
                "chunk_count": int(doc.get("chunk_count", 1) or 1),
                "knowledge_scope": normalize_knowledge_scope(
                    doc.get("knowledge_scope") or "shared"
                ),
                "scope_key": clean_name(doc.get("scope_key") or "")[:256],
                "access_key": self._normalize_access_key(doc)[:512],
                "original_name": (doc.get("original_name") or "")[:255],
                "source_kind": (doc.get("source_kind") or "")[:32],
            }
            for index, doc in enumerate(documents)
        ]

    def load_documents_from_milvus(self, limit: int = 100000):
        if not self.client.has_collection(self.collection_name):
            return []

        rows = self._query_all_by_id(
            collection_name=self.collection_name,
            output_fields=[
                "name",
                "message",
                "source_file",
                "parent_id",
                "source_title",
                "chunk_index",
                "chunk_count",
                "knowledge_scope",
                "scope_key",
                "access_key",
                "original_name",
                "source_kind",
            ],
            limit=limit,
        )
        documents = [
            {
                "name": row.get("name", ""),
                "message": row.get("message", ""),
                "source_file": row.get("source_file", ""),
                "parent_id": row.get("parent_id", ""),
                "source_title": row.get("source_title", ""),
                "chunk_index": int(row.get("chunk_index", 0) or 0),
                "chunk_count": int(row.get("chunk_count", 1) or 1),
                "knowledge_scope": row.get("knowledge_scope", "shared"),
                "scope_key": row.get("scope_key", ""),
                "access_key": row.get("access_key", "shared"),
                "original_name": row.get("original_name", ""),
                "source_kind": row.get("source_kind", ""),
                "is_chunked": True,
            }
            for row in rows
            if row.get("name") and row.get("message")
        ]

        return sorted(
            documents,
            key=lambda item: (
                item.get("name", ""),
                item.get("source_file", ""),
                int(item.get("chunk_index", 0) or 0),
                item.get("message", ""),
            ),
        )

    def list_loaded_files_from_milvus(self, limit: int = 10000):
        if not self.client.has_collection(self.loaded_file_collection_name):
            return []

        rows = self._query_all_by_id(
            collection_name=self.loaded_file_collection_name,
            output_fields=[
                "saved_name",
                "original_name",
                "knowledge_scope",
                "target_role",
                "source_kind",
                "file_size",
                "file_mtime_ns",
                "uploaded_at",
            ],
            limit=limit,
        )
        return [
            {
                "saved_name": row.get("saved_name", ""),
                "original_name": row.get("original_name", ""),
                "knowledge_scope": row.get("knowledge_scope", "shared"),
                "target_role": row.get("target_role", ""),
                "source_kind": row.get("source_kind", ""),
                "size": int(row.get("file_size", 0) or 0),
                "mtime_ns": int(row.get("file_mtime_ns", 0) or 0),
                "uploaded_at": row.get("uploaded_at", ""),
            }
            for row in rows
            if row.get("saved_name")
        ]

    def load_character_documents_from_milvus(self, limit: int = 100000):
        if not self.client.has_collection(self.collection_name):
            return []

        rows = self._query_all_by_id(
            collection_name=self.collection_name,
            output_fields=["name"],
            limit=limit,
        )
        seen = set()
        characters = []
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            characters.append({"name": name})
        return characters

    def _document_exists_in_milvus(self, doc: dict) -> bool:
        if not self.client.has_collection(self.collection_name):
            return False

        escaped_parent_id = self._escape_filter_value(self._build_parent_id(doc))
        escaped_access_key = self._escape_filter_value(self._normalize_access_key(doc))
        chunk_index = int(doc.get("chunk_index", 0) or 0)
        message = doc.get("message", "")

        rows = self.client.query(
            collection_name=self.collection_name,
            filter=(
                f"parent_id == '{escaped_parent_id }' and "
                f"chunk_index == {chunk_index } and "
                f"access_key == '{escaped_access_key }'"
            ),
            output_fields=["id", "message"],
            limit=16,
        )
        return any((row.get("message") or "") == message for row in rows)

    def reset_loaded_files_in_milvus(self, files):
        if self.client.has_collection(self.loaded_file_collection_name):
            self.client.drop_collection(self.loaded_file_collection_name)
        self._create_loaded_file_collection()
        self.append_loaded_files_in_milvus(files)

    def append_loaded_files_in_milvus(self, files) -> int:
        if not files:
            return 0

        if not self.client.has_collection(self.loaded_file_collection_name):
            self._create_loaded_file_collection()

        existing = {
            item.get("saved_name", ""): item
            for item in self.list_loaded_files_from_milvus()
            if item.get("saved_name")
        }
        rows = []
        for item in files:
            saved_name = (item.get("saved_name") or item.get("name") or "").strip()
            if not saved_name:
                continue

            file_size = int(item.get("size") or item.get("file_size") or 0)
            file_mtime_ns = int(item.get("mtime_ns") or item.get("file_mtime_ns") or 0)
            existing_item = existing.get(saved_name)
            if existing_item and (
                int(existing_item.get("size", 0) or 0) == file_size
                and int(existing_item.get("mtime_ns", 0) or 0) == file_mtime_ns
            ):
                continue

            rows.append(
                {
                    "vector": [0.0, 0.0],
                    "saved_name": saved_name,
                    "original_name": (item.get("original_name") or saved_name)[:255],
                    "knowledge_scope": normalize_knowledge_scope(
                        item.get("knowledge_scope") or "shared"
                    ),
                    "target_role": clean_name(item.get("target_role") or "")[:255],
                    "source_kind": (item.get("source_kind") or "")[:32],
                    "file_size": file_size,
                    "file_mtime_ns": file_mtime_ns,
                    "uploaded_at": (item.get("uploaded_at") or "")[:64],
                }
            )

        if not rows:
            return 0

        self.client.insert(collection_name=self.loaded_file_collection_name, data=rows)
        return len(rows)

    def build_index(self, documents):
        chunked_documents = self._chunk_documents(documents)
        print(
            f"知识分块完成: 原始文档数={len (documents )}, "
            f"分块后文档数={len (chunked_documents )}"
        )
        self.documents = []

        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)
        self._create_character_collection()

        if not chunked_documents:
            return

        self._insert_document_batches(chunked_documents)

    def append_documents(self, documents) -> int:
        if not documents:
            return 0

        if not self.client.has_collection(self.collection_name):
            self._create_character_collection()

        incoming_chunks = self._chunk_documents(documents)
        new_documents = []
        for doc in incoming_chunks:
            if self._document_exists_in_milvus(doc):
                continue
            new_documents.append(doc)

        if not new_documents:
            return 0

        self._insert_document_batches(new_documents)
        return len(new_documents)
