from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

try:
    from datasets import Dataset
    from langchain_community.embeddings import HuggingFaceEmbeddings as LangchainHuggingFaceEmbeddings
    from langchain_openai import ChatOpenAI
    from openai import OpenAI
    from ragas import EvaluationDataset, evaluate
    from ragas.llms.base import LangchainLLMWrapper
    from ragas.metrics._answer_relevance import AnswerRelevancy
    from ragas.metrics._context_precision import ContextPrecision
    from ragas.metrics._context_recall import ContextRecall
    from ragas.metrics._faithfulness import Faithfulness
    from ragas.run_config import RunConfig
except ImportError as exc:  # pragma: no cover - import guard for local setup
    missing = exc.name or str(exc)
    raise SystemExit(
        "缺少 RAGAS 评测依赖，请先安装："
        "pip install ragas datasets langchain-community"
        f"。当前缺失模块：{missing}"
    ) from exc

try:
    from ragas.metrics._context_relevancy import ContextRelevancy
except ImportError:
    try:
        from ragas.metrics._context_relevancy import ContextRelevance as ContextRelevancy
    except ImportError:
        try:
            from ragas.metrics import ContextRelevance as ContextRelevancy
        except ImportError:
            ContextRelevancy = None

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings  # noqa: E402
from app.services.intent.analyzer import IntentAnalyzer  # noqa: E402
from app.services.llm.client import OpenAICompatibleLLMClient  # noqa: E402
from app.services.rag.pipeline import RagPipeline  # noqa: E402
from app.services.rag.reranker import BgeReranker  # noqa: E402
from app.services.vector.embedder import BgeM3Embedder  # noqa: E402
from app.services.vector.memory_store import InMemoryVectorStore  # noqa: E402
from app.services.vector.milvus_store import MilvusVectorStore  # noqa: E402

DATASET_PATH = ROOT_DIR / "scripts" / "ragas_dataset.json"
OUTPUT_PATH = ROOT_DIR / "scripts" / "ragas_eval_result.json"
DETAIL_OUTPUT_PATH = ROOT_DIR / "scripts" / "ragas_eval_per_question.json"
SAVE_DETAILS = True


@dataclass
class EvalRecord:
    sample_id: str
    question: str
    ground_truth: str
    doc_ids: list[str] | None
    top_k: int | None
    history: list[dict[str, str]] | None
    metadata: dict[str, Any]


@dataclass
class LocalRagRuntime:
    embedder: BgeM3Embedder
    vector_store: MilvusVectorStore | InMemoryVectorStore
    reranker: BgeReranker
    llm_client: OpenAICompatibleLLMClient
    pipeline: RagPipeline

    def warmup(self) -> None:
        warmup_embedding = self.embedder.embed_query("warmup")
        self.vector_store.warmup(len(warmup_embedding))

    def close(self) -> None:
        self.vector_store.close()
        self.llm_client.close()


def load_dataset(path: Path) -> list[EvalRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Dataset JSON must be a list of samples.")

    records: list[EvalRecord] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Dataset sample #{index} must be an object.")

        question = str(item.get("question") or "").strip()
        ground_truth = str(item.get("ground_truth") or item.get("reference") or "").strip()
        if not question:
            raise ValueError(f"Dataset sample #{index} is missing question.")
        if not ground_truth:
            raise ValueError(f"Dataset sample #{index} is missing ground_truth/reference.")

        doc_ids = item.get("doc_ids")
        if doc_ids is not None and not isinstance(doc_ids, list):
            raise ValueError(f"Dataset sample #{index} doc_ids must be a list or null.")

        history = item.get("history")
        if history is not None and not isinstance(history, list):
            raise ValueError(f"Dataset sample #{index} history must be a list or null.")

        top_k = item.get("top_k")
        if top_k is not None:
            top_k = int(top_k)

        records.append(
            EvalRecord(
                sample_id=str(item.get("id") or f"sample-{index}"),
                question=question,
                ground_truth=ground_truth,
                doc_ids=doc_ids,
                top_k=top_k,
                history=history,
                metadata=item.get("metadata") or {},
            )
        )
    return records


def _normalize_local_model_path(value: str) -> Path:
    raw = str(value).strip()
    cleaned = raw.strip().strip("'\"")
    drive_markers = [idx for idx, char in enumerate(cleaned) if char == ":"]
    if len(drive_markers) > 1:
        raise RuntimeError(f"检测到非法模型路径配置：{raw}。请为每个配置项只保留一个完整路径。")
    return Path(cleaned).expanduser().resolve()


def _find_missing_model_files(model_dir: Path, required_files: tuple[str, ...]) -> list[str]:
    return [name for name in required_files if not (model_dir / name).exists()]


def validate_local_models(settings: Any) -> None:
    embedding_dir = _normalize_local_model_path(settings.embedding_model_name)
    reranker_dir = _normalize_local_model_path(settings.rerank_model_name)
    judge_embedding_value = getattr(settings, "ragas_judge_embedding_model_name", settings.embedding_model_name)
    judge_embedding_dir = _normalize_local_model_path(judge_embedding_value)

    model_checks = [
        (
            "Embedding 模型",
            embedding_dir,
            ("modules.json", "config.json", "tokenizer.json"),
            ("model.safetensors", "pytorch_model.bin"),
        ),
        (
            "Reranker 模型",
            reranker_dir,
            ("config.json", "tokenizer.json"),
            ("model.safetensors", "pytorch_model.bin"),
        ),
    ]

    if judge_embedding_dir != embedding_dir:
        model_checks.append(
            (
                "RAGAS judge embedding 模型",
                judge_embedding_dir,
                ("modules.json", "config.json", "tokenizer.json"),
                ("model.safetensors", "pytorch_model.bin"),
            )
        )

    for label, model_dir, required_files, required_weights in model_checks:
        if not model_dir.exists() or not model_dir.is_dir():
            raise RuntimeError(f"{label}目录不存在：{model_dir}")
        missing_files = _find_missing_model_files(model_dir, required_files)
        if missing_files:
            raise RuntimeError(f"{label}目录不完整：{model_dir}，缺少关键文件：{', '.join(missing_files)}")
        if not any((model_dir / file_name).exists() for file_name in required_weights):
            raise RuntimeError(
                f"{label}目录缺少模型权重：{model_dir}，需要至少一个文件：{', '.join(required_weights)}"
            )


def build_runtime() -> LocalRagRuntime:
    settings = get_settings()
    embedder = BgeM3Embedder(
        model_name=settings.embedding_model_name,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )
    vector_store = InMemoryVectorStore() if settings.vector_backend.lower() == "memory" else MilvusVectorStore(settings)
    reranker = BgeReranker(
        model_name=settings.rerank_model_name,
        device=settings.embedding_device,
        batch_size=settings.rerank_batch_size,
        enabled=settings.rerank_enabled,
    )
    llm_client = OpenAICompatibleLLMClient(settings)
    pipeline = RagPipeline(
        settings=settings,
        intent_analyzer=IntentAnalyzer(),
        embedder=embedder,
        vector_store=vector_store,
        reranker=reranker,
        llm_client=llm_client,
    )
    return LocalRagRuntime(
        embedder=embedder,
        vector_store=vector_store,
        reranker=reranker,
        llm_client=llm_client,
        pipeline=pipeline,
    )


def _summarize_contexts(contexts: list[str]) -> dict[str, int]:
    context_count = len(contexts)
    context_char_total = sum(len(item) for item in contexts)
    context_char_max = max((len(item) for item in contexts), default=0)
    return {
        "context_count": context_count,
        "context_char_total": context_char_total,
        "context_char_max": context_char_max,
    }


def build_ragas_dataset(
    records: list[EvalRecord],
    pipeline_results: list[dict[str, Any]],
) -> tuple[Dataset, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for record, result in zip(records, pipeline_results, strict=False):
        contexts = [
            str(hit.get("text") or "").strip()
            for hit in result["references"]
            if str(hit.get("text") or "").strip()
        ]
        context_stats = _summarize_contexts(contexts)
        rows.append(
            {
                "user_input": record.question,
                "response": result["answer"],
                "retrieved_contexts": contexts,
                "reference": record.ground_truth,
                "question": record.question,
                "answer": result["answer"],
                "contexts": contexts,
                "ground_truth": record.ground_truth,
            }
        )
        details.append(
            {
                "id": record.sample_id,
                "question": record.question,
                "ground_truth": record.ground_truth,
                "answer": result["answer"],
                "normalized_question": result.get("normalized_question"),
                "intent": result.get("intent"),
                "query_variants": result.get("query_variants") or [],
                "optimized_question": result.get("optimized_question"),
                "doc_ids": record.doc_ids,
                "top_k": result.get("top_k"),
                "contexts": contexts,
                "context_stats": context_stats,
                "references": result["references"],
                "timing": result.get("timing") or {},
                "metadata": record.metadata,
            }
        )

    return Dataset.from_list(rows), details


def run_pipeline(records: list[EvalRecord]) -> list[dict[str, Any]]:
    runtime = build_runtime()
    results: list[dict[str, Any]] = []
    try:
        runtime.warmup()
        for idx, record in enumerate(records, start=1):
            print(f"[{idx}/{len(records)}] Evaluating {record.sample_id}: {record.question}")
            answer = runtime.pipeline.answer(
                question=record.question,
                doc_ids=record.doc_ids,
                top_k=record.top_k,
                history=record.history,
            )
            results.append(
                {
                    **answer,
                    "top_k": record.top_k,
                    "references": [
                        {
                            "chunk_id": item.chunk_id,
                            "doc_id": item.doc_id,
                            "page": item.page,
                            "page_end": item.page_end,
                            "score": item.score,
                            "source_file": item.source_file,
                            "text": item.text,
                            "metadata": item.metadata,
                        }
                        for item in answer["references"]
                    ],
                }
            )
        return results
    finally:
        runtime.close()


def _get_setting(settings: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value
    return default


def build_judge_llm(settings: Any):
    model = _get_setting(settings, "ragas_judge_model", "llm_model")
    base_url = _get_setting(settings, "ragas_judge_base_url", "llm_base_url", "openai_base_url")
    api_key = _get_setting(settings, "ragas_judge_api_key", "llm_api_key", "openai_api_key", default="EMPTY")
    timeout = float(_get_setting(settings, "ragas_judge_timeout", "llm_timeout", default=120.0))

    langchain_llm = ChatOpenAI(
        model=model,
        api_key=api_key or "EMPTY",
        base_url=base_url,
        timeout=timeout,
        temperature=0.0,
    )
    return LangchainLLMWrapper(langchain_llm, bypass_n=True)


def build_judge_embeddings(settings: Any):
    model_name = str(
        _normalize_local_model_path(
            _get_setting(settings, "ragas_judge_embedding_model_name", "embedding_model_name")
        )
    )
    device = _get_setting(settings, "ragas_judge_embedding_device", "embedding_device", default="cpu")
    return LangchainHuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={
            "device": device,
            "local_files_only": True,
        },
        encode_kwargs={"normalize_embeddings": True},
    )


def build_metrics(settings: Any) -> tuple[list[Any], list[str], list[str]]:
    evaluator_llm = build_judge_llm(settings)
    evaluator_embeddings = build_judge_embeddings(settings)
    metrics: list[Any] = [
        ContextPrecision(llm=evaluator_llm),
        ContextRecall(llm=evaluator_llm),
        Faithfulness(llm=evaluator_llm),
        AnswerRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings),
    ]
    enabled_metric_names = [
        "context_precision",
        "context_recall",
        "faithfulness",
        "answer_relevancy",
    ]
    skipped_metric_names: list[str] = []
    if ContextRelevancy is not None:
        metrics.insert(2, ContextRelevancy(llm=evaluator_llm))
        enabled_metric_names.insert(2, "context_relevancy")
    else:
        skipped_metric_names.append("context_relevancy")
    return metrics, enabled_metric_names, skipped_metric_names


def build_run_config(settings: Any) -> RunConfig:
    timeout = max(int(_get_setting(settings, "ragas_eval_timeout", default=300)), 60)
    max_workers = max(int(_get_setting(settings, "ragas_eval_max_workers", default=2)), 1)
    max_retries = max(int(_get_setting(settings, "ragas_eval_max_retries", default=4)), 0)
    max_wait = max(int(_get_setting(settings, "ragas_eval_max_wait", default=30)), 1)
    return RunConfig(
        timeout=timeout,
        max_workers=max_workers,
        max_retries=max_retries,
        max_wait=max_wait,
    )


def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {DATASET_PATH}。请先在 scripts/ragas_dataset.json 中准备评测问题集。"
        )

    settings = get_settings()
    validate_local_models(settings)
    records = load_dataset(DATASET_PATH)
    if not records:
        raise ValueError("No evaluation samples found.")

    pipeline_results = run_pipeline(records)
    hf_dataset, details = build_ragas_dataset(records, pipeline_results)
    ragas_dataset = EvaluationDataset.from_hf_dataset(hf_dataset)

    metrics, enabled_metric_names, skipped_metric_names = build_metrics(settings)
    run_config = build_run_config(settings)
    eval_batch_size = _get_setting(settings, "ragas_eval_batch_size")
    raise_exceptions = bool(_get_setting(settings, "ragas_eval_raise_exceptions", default=False))

    print("Running RAGAS metrics...")
    print(f"Enabled metrics: {', '.join(enabled_metric_names)}")
    print(
        "RunConfig: "
        f"timeout={run_config.timeout}s "
        f"max_workers={run_config.max_workers} "
        f"max_retries={run_config.max_retries} "
        f"max_wait={run_config.max_wait}s"
    )
    if eval_batch_size not in (None, ""):
        print(f"Batch size: {int(eval_batch_size)}")
    print(f"Raise exceptions: {raise_exceptions}")
    if skipped_metric_names:
        print(f"Skipped metrics: {', '.join(skipped_metric_names)}")
    evaluate_kwargs: dict[str, Any] = {
        "dataset": ragas_dataset,
        "metrics": metrics,
        "run_config": run_config,
        "raise_exceptions": raise_exceptions,
    }
    if eval_batch_size not in (None, ""):
        evaluate_kwargs["batch_size"] = max(int(eval_batch_size), 1)
    result = evaluate(**evaluate_kwargs)

    result_df = result.to_pandas()
    metric_columns = [
        column
        for column in result_df.columns
        if column not in {"user_input", "retrieved_contexts", "response", "reference"}
    ]
    payload: dict[str, Any] = {
        "dataset_path": str(DATASET_PATH),
        "sample_count": len(records),
        "metrics": result_df.mean(numeric_only=True).to_dict(),
        "enabled_metrics": enabled_metric_names,
        "skipped_metrics": skipped_metric_names,
        "run_config": {
            "timeout": run_config.timeout,
            "max_workers": run_config.max_workers,
            "max_retries": run_config.max_retries,
            "max_wait": run_config.max_wait,
            "batch_size": None if eval_batch_size in (None, "") else max(int(eval_batch_size), 1),
            "raise_exceptions": raise_exceptions,
        },
        "judge": {
            "model": _get_setting(settings, "ragas_judge_model", "llm_model"),
            "base_url": _get_setting(settings, "ragas_judge_base_url", "llm_base_url", "openai_base_url"),
            "embedding_model": _get_setting(settings, "ragas_judge_embedding_model_name", "embedding_model_name"),
            "embedding_device": _get_setting(settings, "ragas_judge_embedding_device", "embedding_device"),
        },
    }
    per_question_payload = {
        "dataset_path": str(DATASET_PATH),
        "sample_count": len(records),
        "metric_columns": metric_columns,
        "questions": [
            {
                "id": detail["id"],
                "question": detail["question"],
                "ground_truth": detail["ground_truth"],
                "answer": detail["answer"],
                "context_stats": detail.get("context_stats") or {},
                **{key: row.get(key) for key in metric_columns},
            }
            for detail, row in zip(details, result_df.to_dict(orient="records"), strict=False)
        ],
    }
    if SAVE_DETAILS:
        payload["details"] = details
        payload["ragas_rows"] = result_df.to_dict(orient="records")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DETAIL_OUTPUT_PATH.write_text(json.dumps(per_question_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Per-question results saved to: {DETAIL_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
