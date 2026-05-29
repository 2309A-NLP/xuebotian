from typing import Dict, List
import traceback

from pymilvus import DataType, Function, FunctionType
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


class VectorStoreCollectionsMixin:
    def _query_all_by_id(
        self,
        collection_name: str,
        output_fields: List[str],
        limit: int,
        batch_size: int = 5000,
    ) -> List[Dict]:
        rows: List[Dict] = []
        last_id = -1

        normalized_batch_size = max(1, min(batch_size, 16000))
        normalized_limit = max(0, limit)

        while len(rows) < normalized_limit:

            current_limit = min(normalized_batch_size, normalized_limit - len(rows))

            query_rows = self.client.query(
                collection_name=collection_name,
                filter=f"id > {last_id }",
                output_fields=["id", *output_fields],
                limit=current_limit,
            )
            if not query_rows:
                break

            rows.extend(query_rows)

            last_id = max(int(row.get("id", last_id) or last_id) for row in query_rows)

            if len(query_rows) < current_limit:
                break

        return rows

    def _get_index_params(self):

        index_params = self.client.prepare_index_params()

        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": self.index_nlist},
        )

        index_params.add_index(field_name="id", index_type="")
        return index_params

    def _get_character_index_params(self):
        index_params = self.client.prepare_index_params()

        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": self.index_nlist},
        )
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        index_params.add_index(field_name="id", index_type="")
        return index_params

    def _create_character_collection(self):

        dim = self.embedding_model.get_dim()

        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field(
            "search_text",
            DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
            analyzer_params={"type": self.text_analyzer},
        )
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("name", DataType.VARCHAR, max_length=256)
        schema.add_field("message", DataType.VARCHAR, max_length=65535)
        schema.add_field("source_file", DataType.VARCHAR, max_length=512)

        schema.add_field("parent_id", DataType.VARCHAR, max_length=512)

        schema.add_field("source_title", DataType.VARCHAR, max_length=255)

        schema.add_field("chunk_index", DataType.INT64)

        schema.add_field("chunk_count", DataType.INT64)

        schema.add_field("knowledge_scope", DataType.VARCHAR, max_length=32)

        schema.add_field("scope_key", DataType.VARCHAR, max_length=256)

        schema.add_field("access_key", DataType.VARCHAR, max_length=512)

        schema.add_field("original_name", DataType.VARCHAR, max_length=255)

        schema.add_field("source_kind", DataType.VARCHAR, max_length=32)
        schema.add_function(
            Function(
                name="search_text_bm25",
                input_field_names=["search_text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )

        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=self._get_character_index_params(),
        )

    def _create_conversation_collection(self):

        dim = self.embedding_model.get_dim()
        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field("session_id", DataType.VARCHAR, max_length=256)
        schema.add_field("user_message", DataType.VARCHAR, max_length=65535)
        schema.add_field("assistant_message", DataType.VARCHAR, max_length=65535)
        schema.add_field("character_name", DataType.VARCHAR, max_length=256)
        schema.add_field("timestamp", DataType.INT64)

        self.client.create_collection(
            collection_name=self.conversation_collection_name,
            schema=schema,
            index_params=self._get_index_params(),
        )

    def _create_loaded_file_collection(self):
        if self.client.has_collection(self.loaded_file_collection_name):
            return

        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=2)
        schema.add_field("saved_name", DataType.VARCHAR, max_length=255)
        schema.add_field("original_name", DataType.VARCHAR, max_length=255)
        schema.add_field("knowledge_scope", DataType.VARCHAR, max_length=32)
        schema.add_field("target_role", DataType.VARCHAR, max_length=255)
        schema.add_field("source_kind", DataType.VARCHAR, max_length=32)
        schema.add_field("file_size", DataType.INT64)
        schema.add_field("file_mtime_ns", DataType.INT64)
        schema.add_field("uploaded_at", DataType.VARCHAR, max_length=64)

        self.client.create_collection(
            collection_name=self.loaded_file_collection_name,
            schema=schema,
            index_params=self._get_index_params(),
        )

    def has_character_collection(self) -> bool:
        try:
            return self.client.has_collection(self.collection_name)
        except Exception:
            logger.error(
                "检查知识库集合是否存在失败，已降级返回 False。collection=%s\n%s",
                self.collection_name,
                traceback.format_exc(),
            )
            return False

    def character_collection_uses_builtin_bm25(self) -> bool:
        if not self.has_character_collection():
            return False
        try:
            details = self.client.describe_collection(
                collection_name=self.collection_name
            )
        except Exception:
            logger.error(
                "读取知识库集合结构失败，已判定为未启用内置 BM25。collection=%s\n%s",
                self.collection_name,
                traceback.format_exc(),
            )
            return False

        fields = {
            (field.get("name") or "").strip(): field
            for field in details.get("fields", [])
            if field.get("name")
        }
        if not {"vector", "search_text", "sparse", "message", "name"}.issubset(fields):
            return False

        functions = details.get("functions") or []
        return bool(functions)

    def has_loaded_file_collection(self) -> bool:
        try:
            return self.client.has_collection(self.loaded_file_collection_name)
        except Exception:
            logger.error(
                "检查已加载文件集合是否存在失败，已降级返回 False。collection=%s\n%s",
                self.loaded_file_collection_name,
                traceback.format_exc(),
            )
            return False

    def ping(self) -> bool:
        try:

            self.client.list_collections()
            return True
        except Exception:
            logger.error(
                "Milvus 连通性检查失败，已降级返回 False。\n%s",
                traceback.format_exc(),
            )
            return False
