from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI


DEFAULT_QUESTIONS_FILE = Path(__file__).with_name("questions.txt")
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("answers.json")
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_SYSTEM_PROMPT = "你是一个有帮助的助手，请直接回答用户问题。若不确定，请明确说明不确定。"
DEFAULT_MAX_WORKERS = 5
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_TOKENS = 1200
DEFAULT_TEMPERATURE = 0.2


def load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


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


def build_client(api_key: str, base_url: str, timeout: int) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )


def ask_one_question(
    question: str,
    system_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> str:
    client = build_client(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )
        return response.choices[0].message.content or ""
    finally:
        client.close()


def ask_questions(
    questions: list[str],
    system_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    max_workers: int,
) -> dict[str, str]:
    answers: dict[str, str] = {}
    total = len(questions)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_question = {
            executor.submit(
                ask_one_question,
                question,
                system_prompt,
                api_key,
                base_url,
                model,
                timeout,
                max_tokens,
                temperature,
            ): question
            for question in questions
        }

        completed = 0
        for future in as_completed(future_to_question):
            question = future_to_question[future]
            completed += 1
            try:
                answer = future.result().strip()
                answers[question] = answer
                print(f"[{completed}/{total}] 已完成: {question}")
            except Exception as exc:
                answers[question] = f"请求失败: {exc}"
                print(f"[{completed}/{total}] 失败: {question} | {exc}")

    return {question: answers[question] for question in questions}


def save_answers(output_file: Path, answers: dict[str, str]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(answers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="直接请求大模型 API，批量回答问题，并保存为 JSON。",
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
        help="输出 JSON 文件路径，默认写入 duibi/answers.json",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="环境变量文件路径，默认读取项目根目录 .env",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API Key，未传则读取环境变量 LLM_API_KEY 或 OPENAI_API_KEY",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="接口地址，未传则读取环境变量 LLM_BASE_URL 或 OPENAI_BASE_URL",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="模型名，未传则读取环境变量 LLM_MODEL 或 OPENAI_MODEL",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="请求超时时间，单位秒",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="最大输出 token 数",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="采样温度",
    )
    parser.add_argument(
        "--system-prompt",
        default=DEFAULT_SYSTEM_PROMPT,
        help="可选系统提示词",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="并发请求数，默认 5",
    )
    return parser


def resolve_runtime_args(args: argparse.Namespace) -> dict[str, str | int | float]:
    load_env_file(args.env_file)

    api_key = args.api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = args.model or os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL")
    timeout = args.timeout or int(os.getenv("LLM_TIMEOUT", DEFAULT_TIMEOUT))
    max_tokens = args.max_tokens or int(os.getenv("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    temperature = args.temperature
    if temperature is None:
        temperature = float(os.getenv("LLM_TEMPERATURE", DEFAULT_TEMPERATURE))

    if not api_key:
        raise ValueError("缺少 API Key，请通过 --api-key 或环境变量 LLM_API_KEY / OPENAI_API_KEY 提供")
    if not base_url:
        raise ValueError("缺少 base_url，请通过 --base-url 或环境变量 LLM_BASE_URL / OPENAI_BASE_URL 提供")
    if not model:
        raise ValueError("缺少 model，请通过 --model 或环境变量 LLM_MODEL / OPENAI_MODEL 提供")

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": timeout,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.max_workers < 1:
        raise ValueError("--max-workers 必须大于等于 1")

    questions = load_questions(args.questions)
    runtime = resolve_runtime_args(args)
    answers = ask_questions(
        questions=questions,
        system_prompt=args.system_prompt,
        api_key=str(runtime["api_key"]),
        base_url=str(runtime["base_url"]),
        model=str(runtime["model"]),
        timeout=int(runtime["timeout"]),
        max_tokens=int(runtime["max_tokens"]),
        temperature=float(runtime["temperature"]),
        max_workers=min(args.max_workers, len(questions)),
    )
    save_answers(args.output, answers)

    print(f"已保存 {len(answers)} 条结果到: {args.output}")


if __name__ == "__main__":
    main()
