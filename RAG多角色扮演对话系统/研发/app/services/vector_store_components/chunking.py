import re
from typing import Dict, List, Optional

from app.services.data_loader import (
    build_access_key,
    clean_name,
    normalize_knowledge_scope,
)


class VectorStoreChunkingMixin:

    def _tokenize(self, text: str) -> List[str]:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not normalized:
            return []

        tokens: List[str] = []

        augmented_seen = set()

        def add_augmented_token(token: str) -> None:
            cleaned = token.strip()
            if not cleaned or cleaned in augmented_seen:
                return
            augmented_seen.add(cleaned)
            tokens.append(cleaned)

        for token in self._jieba_cut(normalized):
            cleaned = token.strip()
            if not cleaned:
                continue

            if len(cleaned) == 1 and not re.search(
                r"[\u4e00-\u9fffA-Za-z0-9]", cleaned
            ):
                continue

            tokens.append(cleaned)

        for token in re.findall(r"[a-z0-9]+", normalized):
            add_augmented_token(token)

        cjk_text = re.sub(r"[^\u4e00-\u9fff]", "", normalized)
        ngram_budget = 256

        for n in (2, 3):
            if len(cjk_text) < n:
                continue
            for index in range(len(cjk_text) - n + 1):
                add_augmented_token(cjk_text[index : index + n])
                ngram_budget -= 1
                if ngram_budget <= 0:
                    break
            if ngram_budget <= 0:
                break

        return tokens or normalized.split()

    def _escape_filter_value(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _split_sentences(self, text: str) -> List[str]:
        if not text:
            return []
        parts = re.split(
            r"(?:\n+|(?<=[\u3002\uFF01\uFF1F!?;\uFF1B\u2026])\s*)",
            text,
        )
        return [part.strip() for part in parts if part.strip()]

    def _slice_long_text(self, text: str) -> List[str]:
        if not text:
            return []

        step = max(1, self.chunk_size - self.chunk_overlap)
        chunks: List[str] = []
        start = 0
        while start < len(text):
            chunk = text[start : start + self.chunk_size].strip()
            if chunk:
                chunks.append(chunk)
            if start + self.chunk_size >= len(text):
                break
            start += step
        return chunks

    def _chunk_text(self, text: str) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]

        chunks: List[str] = []
        current = ""
        paragraphs = [
            part.strip() for part in re.split(r"\n{2,}", text) if part.strip()
        ]
        if not paragraphs:
            paragraphs = [text]

        for paragraph in paragraphs:
            sentences = self._split_sentences(paragraph) or [paragraph]
            for sentence in sentences:
                if len(sentence) > self.chunk_size:
                    if current:
                        chunks.append(current.strip())
                        current = ""
                    chunks.extend(self._slice_long_text(sentence))
                    continue

                candidate = f"{current }\n{sentence }".strip() if current else sentence
                if len(candidate) <= self.chunk_size:
                    current = candidate
                    continue

                chunks.append(current.strip())
                overlap_text = (
                    current[-self.chunk_overlap :] if self.chunk_overlap else ""
                )
                current = f"{overlap_text }\n{sentence }".strip()
                if len(current) > self.chunk_size:
                    chunks.extend(self._slice_long_text(current))
                    current = ""

        if current:
            chunks.append(current.strip())

        deduplicated_chunks: List[str] = []
        seen = set()
        for chunk in chunks:
            normalized = chunk.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduplicated_chunks.append(normalized)
        return deduplicated_chunks or [text[: self.chunk_size]]

    def _build_parent_id(self, doc: Dict) -> str:
        parent_id = (doc.get("parent_id") or "").strip()
        if parent_id:
            return parent_id
        name = (doc.get("name") or "").strip()
        source_file = (doc.get("source_file") or "").strip()
        return f"{source_file or 'memory'}::{name }"[:512]

    def _normalize_access_key(self, doc: Dict) -> str:
        access_key = (doc.get("access_key") or "").strip()
        if access_key:
            return access_key
        scope = doc.get("knowledge_scope") or "shared"
        scope_key = doc.get("scope_key") or ""
        return build_access_key(scope, scope_key)

    def _resolve_access_keys(self, character_name: Optional[str]) -> List[str]:
        keys = ["shared"]
        normalized_name = clean_name(character_name or "")
        if normalized_name:
            keys.append(f"private::{normalized_name }")
        return keys

    def _is_accessible(self, doc: Dict, character_name: Optional[str]) -> bool:
        return self._normalize_access_key(doc) in self._resolve_access_keys(
            character_name
        )

    def _chunk_documents(self, documents: List[Dict]) -> List[Dict]:
        chunked_documents: List[Dict] = []
        for doc in documents:
            name = (doc.get("name") or "").strip()
            message = (doc.get("message") or "").strip()
            if not name or not message:
                continue

            chunks = self._chunk_text(message)
            source_file = (doc.get("source_file") or "").strip()
            parent_id = self._build_parent_id(doc)
            source_title = (doc.get("source_title") or "").strip()
            summary = (doc.get("summary") or "").strip()
            knowledge_scope = normalize_knowledge_scope(
                doc.get("knowledge_scope") or "shared"
            )
            scope_key = clean_name(doc.get("scope_key") or "")
            access_key = self._normalize_access_key(doc)
            original_name = (doc.get("original_name") or source_file).strip()
            source_kind = (doc.get("source_kind") or "").strip()

            for chunk_index, chunk in enumerate(chunks):
                chunked_documents.append(
                    {
                        "name": name,
                        "message": chunk,
                        "source_file": source_file,
                        "parent_id": parent_id,
                        "source_title": source_title,
                        "summary": summary,
                        "chunk_index": chunk_index,
                        "chunk_count": len(chunks),
                        "knowledge_scope": knowledge_scope,
                        "scope_key": scope_key,
                        "access_key": access_key,
                        "original_name": original_name,
                        "source_kind": source_kind,
                        "is_chunked": True,
                    }
                )
        return chunked_documents

    def _has_chunk_metadata(self, doc: Dict) -> bool:
        return "chunk_index" in doc and "chunk_count" in doc

    def _has_parent_metadata(self, doc: Dict) -> bool:
        return bool((doc.get("parent_id") or "").strip())

    def documents_require_rechunking(self, documents: List[Dict]) -> bool:
        if not documents:
            return False
        return any(
            not self._has_chunk_metadata(doc) or not self._has_parent_metadata(doc)
            for doc in documents
        )
