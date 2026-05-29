import argparse
import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from langchain_core.outputs import Generation, LLMResult
from langchain_core.prompt_values import ChatPromptValue, PromptValue, StringPromptValue


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


DEFAULT_INPUT_PATH = Path(__file__).with_name("ragas_eval_samples.jsonl")
DEFAULT_OUTPUT_PATH = Path(__file__).with_name("ragas_eval_report.json")
DEFAULT_LLM_MODE = "online"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 ragas 评测脚本。")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"输入 JSONL 路径，默认: {DEFAULT_INPUT_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"输出评测结果 JSON 路径，默认: {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("offline", "online"),
        default=DEFAULT_LLM_MODE,
        help="评测时使用项目里的离线或在线聊天模型。",
    )
    return parser.parse_args()


def load_jsonl(input_path: Path) -> List[Dict]:
    if not input_path.exists():
        raise FileNotFoundError(f"未找到输入文件: {input_path}")

    samples: List[Dict] = []
    with input_path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            contexts = item.get("contexts") or []
            if not isinstance(contexts, list):
                raise ValueError(f"第 {line_number} 行的 contexts 必须是列表。")
            sample = {
                "question": item.get("question", ""),
                "answer": item.get("answer", ""),
                "contexts": [str(text) for text in contexts],
                "ground_truth": item.get("ground_truth", ""),
            }
            sample["user_input"] = sample["question"]
            sample["response"] = sample["answer"]
            sample["retrieved_contexts"] = sample["contexts"]
            sample["reference"] = sample["ground_truth"]
            samples.append(sample)

    if not samples:
        raise RuntimeError("输入数据为空，无法执行 ragas 评测。")
    return samples


def import_dependencies():
    try:
        from datasets import Dataset
    except ImportError as exc:
        raise RuntimeError(
            "缺少 datasets 依赖，请执行: pip install datasets"
        ) from exc

    try:
        from ragas import evaluate
        from ragas import metrics as ragas_metrics
    except ImportError as exc:
        raise RuntimeError("缺少 ragas 依赖，请执行: pip install ragas") from exc

    try:
        from ragas.embeddings import BaseRagasEmbeddings
        from ragas.llms import BaseRagasLLM, llm_factory
    except ImportError as exc:
        raise RuntimeError("当前 ragas 版本不支持自定义 llm/embeddings 适配。") from exc

    return (
        Dataset,
        evaluate,
        ragas_metrics,
        BaseRagasLLM,
        BaseRagasEmbeddings,
        llm_factory,
    )


def resolve_metric(module, candidates: Sequence[str]) -> Tuple[str, object]:
    for name in candidates:
        metric = getattr(module, name, None)
        if metric is not None:
            if isinstance(metric, type):
                return name, metric()
            return name, metric
    raise AttributeError(f"未找到可用 metric: {candidates}")


def build_metrics(ragas_metrics) -> List[Tuple[str, object]]:
    return [
        resolve_metric(ragas_metrics, ("faithfulness", "Faithfulness")),
        resolve_metric(
            ragas_metrics,
            (
                "answer_relevancy",
                "answer_relevance",
                "AnswerRelevancy",
                "ResponseRelevancy",
            ),
        ),
        resolve_metric(
            ragas_metrics,
            ("context_precision", "ContextPrecision"),
        ),
        resolve_metric(
            ragas_metrics,
            ("context_recall", "ContextRecall"),
        ),
        resolve_metric(
            ragas_metrics,
            ("answer_correctness", "AnswerCorrectness"),
        ),
    ]


def _to_json_safe(value: Any):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _is_missing_score(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _build_metric_failure_stats(result) -> Dict[str, Dict[str, int]]:
    scores = getattr(result, "scores", None)
    if not isinstance(scores, list):
        return {}

    metric_names = []
    if scores and isinstance(scores[0], dict):
        metric_names = list(scores[0].keys())

    stats: Dict[str, Dict[str, int]] = {}
    for metric_name in metric_names:
        missing_count = 0
        valid_count = 0
        for row in scores:
            value = row.get(metric_name)
            if _is_missing_score(value):
                missing_count += 1
            else:
                valid_count += 1
        stats[metric_name] = {
            "valid_samples": valid_count,
            "failed_samples": missing_count,
        }
    return stats


def normalize_result(result) -> Dict:
    summary: Dict[str, Any] = {}

    repr_dict = getattr(result, "_repr_dict", None)
    if isinstance(repr_dict, dict):
        summary.update({key: _to_json_safe(value) for key, value in repr_dict.items()})

    scores = getattr(result, "scores", None)
    if isinstance(scores, list):
        summary["score_rows"] = len(scores)
        summary["metric_failures"] = _build_metric_failure_stats(result)

    traces = getattr(result, "traces", None)
    if isinstance(traces, list):
        summary["trace_count"] = len(traces)

    run_id = getattr(result, "run_id", None)
    if run_id is not None:
        summary["run_id"] = str(run_id)

    if summary:
        return _to_json_safe(summary)

    if isinstance(result, dict):
        return _to_json_safe(result)

    return {"result": str(result)}


def _prompt_to_messages(prompt: PromptValue) -> List[Dict[str, str]]:
    if isinstance(prompt, ChatPromptValue):
        messages: List[Dict[str, str]] = []
        for message in prompt.to_messages():
            role = getattr(message, "type", "human")
            content = message.content
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                )
            if role in ("human", "user"):
                normalized_role = "user"
            elif role in ("ai", "assistant"):
                normalized_role = "assistant"
            elif role == "system":
                normalized_role = "system"
            else:
                normalized_role = "user"
            messages.append({"role": normalized_role, "content": str(content)})
        return messages

    if isinstance(prompt, StringPromptValue):
        return [{"role": "user", "content": prompt.to_string()}]

    return [{"role": "user", "content": prompt.to_string()}]


def build_ragas_llm(BaseRagasLLM, llm_factory, llm_mode: str):
    if llm_mode == "online":
        from openai import AsyncOpenAI

        from app.core.config import (
            ONLINE_LLM_API_KEY,
            ONLINE_LLM_BASE_URL,
            ONLINE_LLM_MODEL,
        )

        normalized_base_url = (ONLINE_LLM_BASE_URL or "").rstrip("/")
        if normalized_base_url.endswith("/chat/completions"):
            normalized_base_url = normalized_base_url[: -len("/chat/completions")]

        client = AsyncOpenAI(
            api_key=ONLINE_LLM_API_KEY,
            base_url=normalized_base_url,
        )
        return llm_factory(
            ONLINE_LLM_MODEL,
            provider="openai",
            client=client,
        )

    from app.services.llm import ChatRouterLLM

    class ProjectRagasLLM(BaseRagasLLM):
        def __init__(self, mode: str):
            super().__init__()
            self.mode = mode
            self.router = ChatRouterLLM()

        def generate_text(
            self,
            prompt: PromptValue,
            n: int = 1,
            temperature: float = 0.01,
            stop=None,
            callbacks=None,
        ) -> LLMResult:
            del temperature, stop, callbacks
            messages = _prompt_to_messages(prompt)
            generations = []
            for _ in range(max(1, n)):
                content = self.router.chat(messages, mode=self.mode)
                generations.append(
                    [Generation(text=content, generation_info={"finish_reason": "stop"})]
                )
            if n > 1:
                generations = [[item[0] for item in generations]]
            return LLMResult(generations=generations)

        async def agenerate_text(
            self,
            prompt: PromptValue,
            n: int = 1,
            temperature: float = 0.01,
            stop=None,
            callbacks=None,
        ) -> LLMResult:
            return await asyncio.to_thread(
                self.generate_text,
                prompt,
                n,
                temperature,
                stop,
                callbacks,
            )

        def is_finished(self, response: LLMResult) -> bool:
            return True

    return ProjectRagasLLM(llm_mode)


def build_ragas_embeddings(BaseRagasEmbeddings):
    from app.services.embedding import EmbeddingModel

    class ProjectRagasEmbeddings(BaseRagasEmbeddings):
        def __init__(self):
            super().__init__()
            self.embedding_model = EmbeddingModel()

        def embed_query(self, text: str) -> List[float]:
            return self.embedding_model.encode([text])[0]

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            return self.embedding_model.encode(texts)

        async def aembed_query(self, text: str) -> List[float]:
            return await asyncio.to_thread(self.embed_query, text)

        async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
            return await asyncio.to_thread(self.embed_documents, texts)

    return ProjectRagasEmbeddings()


def main() -> None:
    args = parse_args()
    samples = load_jsonl(args.input)
    (
        Dataset,
        evaluate,
        ragas_metrics,
        BaseRagasLLM,
        BaseRagasEmbeddings,
        llm_factory,
    ) = import_dependencies()
    metric_pairs = build_metrics(ragas_metrics)
    ragas_llm = build_ragas_llm(BaseRagasLLM, llm_factory, args.llm_mode)
    ragas_embeddings = build_ragas_embeddings(BaseRagasEmbeddings)

    dataset = Dataset.from_list(samples)
    result = evaluate(
        dataset=dataset,
        metrics=[metric for _, metric in metric_pairs],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
    )

    summary = normalize_result(result)
    summary["metrics"] = [name for name, _ in metric_pairs]
    summary["sample_count"] = len(samples)
    summary["input_path"] = str(args.input)
    summary["llm_mode"] = args.llm_mode

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[done] 评测完成，样本数: {len(samples)}")
    print(f"[done] LLM 模式: {args.llm_mode}")
    for name, _ in metric_pairs:
        if name in summary:
            print(f"{name}: {summary[name]}")
    print(f"[done] 结果已写入: {args.output}")


if __name__ == "__main__":
    main()
