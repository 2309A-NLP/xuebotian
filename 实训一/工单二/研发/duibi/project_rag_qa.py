from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


DEFAULT_QUESTIONS_FILE = Path(__file__).with_name("questions.txt")
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("rag_answers.json")
DEFAULT_CHAT_URL = "http://127.0.0.1:8000/api/chat"
DEFAULT_TIMEOUT = 120


def load_questions(questions_file: Path) -> list[str]:
    if not questions_file.exists():
        raise FileNotFoundError(f"问题文件不存在: {questions_file}")

    questions: list[str] = []
    for line in questions_file.read_text(encoding="utf-8").splitlines():
        question = line.strip()
        if not question or question.startswith("#"):
            continue
        questions.append(question)

    if not questions:
        raise ValueError(f"问题文件为空: {questions_file}")

    return questions


def ask_one_question(
    client: httpx.Client,
    chat_url: str,
    question: str,
    doc_ids: list[str] | None,
    top_k: int | None,
) -> str:
    payload: dict[str, object] = {"question": question}
    if doc_ids:
        payload["doc_ids"] = doc_ids
    if top_k is not None:
        payload["top_k"] = top_k

    response = client.post(chat_url, json=payload)
    response.raise_for_status()
    data = response.json()

    if not data.get("success", True):
        raise ValueError(data.get("message", "接口返回失败"))

    answer = data.get("data", {}).get("answer")
    if not isinstance(answer, str):
        raise ValueError("接口返回中缺少 data.answer")
    return answer.strip()


def ask_questions(
    questions: list[str],
    chat_url: str,
    timeout: int,
    doc_ids: list[str] | None,
    top_k: int | None,
) -> dict[str, str]:
    answers: dict[str, str] = {}

    with httpx.Client(timeout=timeout) as client:
        total = len(questions)
        for index, question in enumerate(questions, start=1):
            try:
                answers[question] = ask_one_question(
                    client=client,
                    chat_url=chat_url,
                    question=question,
                    doc_ids=doc_ids,
                    top_k=top_k,
                )
                print(f"[{index}/{total}] 已完成: {question}")
            except Exception as exc:
                answers[question] = f"请求失败: {exc}"
                print(f"[{index}/{total}] 失败: {question} | {exc}")

    return answers


def save_answers(output_file: Path, answers: dict[str, str]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(answers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="批量请求本项目的 /api/chat 接口，并将问答结果保存为 JSON。",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS_FILE,
        help="问题文件路径，默认读取 duibi/questions.txt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="输出 JSON 文件路径，默认写入 duibi/rag_answers.json",
    )
    parser.add_argument(
        "--chat-url",
        default=DEFAULT_CHAT_URL,
        help="聊天接口地址，默认 http://127.0.0.1:8000/api/chat",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="请求超时时间，单位秒，默认 120",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="可选，传给接口的 top_k 参数",
    )
    parser.add_argument(
        "--doc-id",
        action="append",
        default=None,
        help="可选，限制检索文档 ID。可重复传入多个 --doc-id",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.timeout <= 0:
        raise ValueError("--timeout 必须大于 0")
    if args.top_k is not None and args.top_k <= 0:
        raise ValueError("--top-k 必须大于 0")

    questions = load_questions(args.questions)
    answers = ask_questions(
        questions=questions,
        chat_url=args.chat_url,
        timeout=args.timeout,
        doc_ids=args.doc_id,
        top_k=args.top_k,
    )
    save_answers(args.output, answers)
    print(f"已保存 {len(answers)} 条结果到: {args.output}")


if __name__ == "__main__":
    main()
