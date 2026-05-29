import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import DATA_DIR
from app.services.ingestion.loader import load_single_data_file


DEFAULT_OUTPUT_PATH = Path(__file__).with_name("ragas_eval_samples.jsonl")
DEFAULT_TOP_K = 3

DEFAULT_CASES: List[Dict[str, str]] = [
    {
        "question": "什么是慢支？",
        "ground_truth": "慢支是气管、支气管黏膜及其周围组织的慢性非特异性炎症，临床上以咳嗽、咳痰为主要症状，或伴有喘息，每年持续3个月或更久，连续2年或以上，并需排除其他类似疾病。",
    },
    {
        "question": "COPD 是什么？",
        "ground_truth": "COPD 即慢阻肺，是以持续气流受限为特征、可预防和治疗的疾病，气流受限多呈进行性发展，并与气道和肺组织对有害气体或颗粒的异常慢性炎症反应有关。",
    },
    {
        "question": "AECOPD 指什么？",
        "ground_truth": "AECOPD 指慢阻肺急性加重，表现为咳嗽、咳痰、呼吸困难较平时加重，或痰量增多、出现黄痰，通常提示需要调整治疗方案。",
    },
    {
        "question": "支气管哮喘的主要临床表现是什么？",
        "ground_truth": "支气管哮喘是多种细胞和细胞组分参与的气道慢性炎症性疾病，临床常表现为反复发作的喘息、气急、胸闷或咳嗽，常在夜间及凌晨发作或加重。",
    },
    {
        "question": "什么是 AHR？",
        "ground_truth": "AHR 是气道高反应性，指气道对变应原、理化因素、运动、药物等刺激因子呈现高度敏感状态，是哮喘的基本特征。",
    },
    {
        "question": "CAP 的定义是什么？",
        "ground_truth": "CAP 是社区获得性肺炎，指在医院外罹患的感染性肺实质炎症，也包括具有明确潜伏期的病原体感染而在入院后潜伏期内发病的肺炎。",
    },
    {
        "question": "HAP 的定义是什么？",
        "ground_truth": "HAP 是医院获得性肺炎，指患者入院时不存在也不在潜伏期，而在入院48小时后于医院内发生的肺炎。",
    },
    {
        "question": "什么是肺动脉高压？它的血流动力学诊断标准是什么？",
        "ground_truth": "肺动脉高压是由多种已知或未知原因引起的肺动脉压力异常升高的病理生理状态，其血流动力学诊断标准是在海平面、静息状态下右心导管测得平均肺动脉压大于或等于25 mmHg。",
    },
    {
        "question": "什么是肺心病？",
        "ground_truth": "肺心病是由支气管-肺组织、胸廓或肺血管病变导致肺血管阻力增加，进而产生肺动脉高压并引起右心室结构和功能改变的疾病。",
    },
    {
        "question": "什么是 SAHS？",
        "ground_truth": "SAHS 是睡眠呼吸暂停低通气综合征，指多种原因导致睡眠状态下反复出现呼吸暂停和低通气，引起间歇性低氧血症、高碳酸血症及睡眠结构紊乱的一组临床综合征。",
    },
]


class InMemoryConversationMemory:
    def __init__(self, max_rounds: int = 10):
        self.max_rounds = max_rounds
        self._store: Dict[str, List[Dict]] = {}

    def get_recent_turns(self, session_id: str) -> List[Dict]:
        return list(self._store.get(session_id, []))

    def add_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        character_name: str = None,
    ) -> None:
        turns = self._store.setdefault(session_id, [])
        turns.append(
            {
                "user_message": user_message,
                "assistant_message": assistant_message,
                "character_name": character_name,
            }
        )
        if len(turns) > self.max_rounds:
            self._store[session_id] = turns[-self.max_rounds :]

    def get_last_character(self, session_id: str, turns: List[Dict] = None):
        turns = turns if turns is not None else self.get_recent_turns(session_id)
        for turn in reversed(turns):
            character_name = turn.get("character_name")
            if character_name:
                return character_name
        return None

    def get_message_history(
        self, session_id: str, turns: List[Dict] = None
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        source_turns = turns if turns is not None else self.get_recent_turns(session_id)
        for turn in source_turns:
            user_message = (turn.get("user_message") or "").strip()
            assistant_message = (turn.get("assistant_message") or "").strip()
            if user_message:
                messages.append({"role": "user", "content": user_message})
            if assistant_message:
                messages.append({"role": "assistant", "content": assistant_message})
        return messages

    def clear_history(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def ping(self) -> bool:
        return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="构建用于 ragas 的 RAG 评测数据集（JSONL）。"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"输出 JSONL 路径，默认: {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--chat-mode",
        default="offline",
        choices=["offline", "online"],
        help="调用项目 RAG 时使用的模型模式。",
    )
    parser.add_argument(
        "--backend",
        default="direct",
        choices=["direct", "mock"],
        help="direct=直接调用项目 RAG；mock=本地检索并用 ground_truth 占位。",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="写入数据集的上下文片段数量。",
    )
    return parser.parse_args()


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.lower())
    parts = re.findall(r"[\u4e00-\u9fff]{1,4}|[a-z0-9]+", normalized)
    return [part for part in parts if part.strip()]


def load_documents() -> List[Dict]:
    documents: List[Dict] = []
    for file_path in sorted(DATA_DIR.iterdir()):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in {".json", ".txt", ".pdf", ".docx"}:
            continue
        try:
            documents.extend(load_single_data_file(file_path))
            print(f"[ok] 已加载知识文件: {file_path.name}")
        except Exception as exc:
            print(f"[warn] 跳过无法解析的文件: {file_path.name} -> {exc}")
    if not documents:
        raise RuntimeError("未加载到任何知识文档，请先检查 data 目录和依赖环境。")
    return documents


def build_rag_system():
    from app.services.rag import RAGSystem

    rag = RAGSystem()
    rag.memory = InMemoryConversationMemory(
        max_rounds=getattr(rag.memory, "max_rounds", 10)
    )
    rag.response_cache.enabled = False
    if not rag.vector_store.has_character_collection():
        raise RuntimeError(
            "Milvus 中未找到现有知识库集合，请先完成入库后再运行 direct 模式。"
        )
    return rag


def score_document(query: str, document: Dict) -> float:
    query_terms = tokenize(query)
    message = document.get("message", "")
    name = document.get("name", "")
    haystack = f"{name}\n{message}".lower()
    score = 0.0
    for term in query_terms:
        if term and term in haystack:
            score += max(1.0, len(term) / 2)
    if name and name.lower() in query.lower():
        score += 2.0
    return score


def retrieve_contexts_locally(
    documents: Sequence[Dict], query: str, top_k: int
) -> List[str]:
    ranked = sorted(
        documents,
        key=lambda item: score_document(query, item),
        reverse=True,
    )
    contexts: List[str] = []
    for item in ranked:
        text = (item.get("message") or "").strip()
        if not text:
            continue
        contexts.append(text[:1200])
        if len(contexts) >= top_k:
            break
    return contexts


def build_samples_with_rag(
    rag,
    cases: Iterable[Dict[str, str]],
    chat_mode: str,
    top_k: int,
) -> List[Dict]:
    samples: List[Dict] = []
    for index, case in enumerate(cases, start=1):
        session_id = f"ragas-eval-{index}"
        result = rag.chat(
            query=case["question"],
            session_id=session_id,
            character_name=case.get("character_name"),
            chat_mode=chat_mode,
        )
        contexts = [
            (item.get("text") or "").strip()
            for item in result.get("sources", [])
            if (item.get("text") or "").strip()
        ][:top_k]
        samples.append(
            {
                "question": case["question"],
                "answer": result.get("response", "").strip(),
                "contexts": contexts,
                "ground_truth": case["ground_truth"],
                "retrieval_query": case["question"],
            }
        )
        print(
            f"[ok] 已生成样本 {index}: "
            f"answer_len={len(samples[-1]['answer'])}, contexts={len(contexts)}"
        )
    return samples


def refresh_contexts_only(
    rag,
    input_path: Path,
    chat_mode: str,
    top_k: int,
) -> List[Dict]:
    if not input_path.exists():
        raise FileNotFoundError(f"未找到输入数据集: {input_path}")

    updated_samples: List[Dict] = []
    with input_path.open("r", encoding="utf-8") as file:
        for index, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            question = item.get("question", "")
            if not question:
                raise ValueError(f"第 {index} 行缺少 question")

            recent_turns: List[Dict] = []
            _detected_character, _retrieval_query, reranked_docs = rag._search_role_knowledge(
                query=question,
                requested_character=item.get("character_name"),
                session_id=f"ragas-refresh-{index}",
                recent_turns=recent_turns,
                chat_mode=chat_mode,
            )
            contexts = [
                (doc.get("message") or "").strip()
                for doc in reranked_docs
                if (doc.get("message") or "").strip()
            ][:top_k]

            item["contexts"] = contexts
            updated_samples.append(item)
            print(f"[ok] 已刷新第 {index} 条 contexts: {len(contexts)}")

    return updated_samples


def build_samples_with_mock(
    documents: Sequence[Dict], cases: Iterable[Dict[str, str]], top_k: int
) -> List[Dict]:
    samples: List[Dict] = []
    for case in cases:
        samples.append(
            {
                "question": case["question"],
                "answer": case["ground_truth"],
                "contexts": retrieve_contexts_locally(documents, case["question"], top_k),
                "ground_truth": case["ground_truth"],
                "retrieval_query": case["question"],
            }
        )
    return samples


def write_jsonl(output_path: Path, samples: Sequence[Dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for item in samples:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()

    if args.backend == "direct":
        rag = build_rag_system()
        samples = refresh_contexts_only(
            rag=rag,
            input_path=args.output,
            chat_mode=args.chat_mode,
            top_k=args.top_k,
        )
    else:
        documents = load_documents()
        samples = build_samples_with_mock(
            documents=documents,
            cases=DEFAULT_CASES,
            top_k=args.top_k,
        )

    write_jsonl(args.output, samples)
    print(f"[done] 已写入 {len(samples)} 条样本到: {args.output}")


if __name__ == "__main__":
    main()
