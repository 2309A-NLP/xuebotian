#!/usr/bin/env python3
"""Simple load test script for the RAG chat API."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, Optional

import requests


DEFAULT_QUERIES = [
    "冠心病的预防措施是什么呢",
]


@dataclass
class Result:
    ok: bool
    latency: float
    ttfb: Optional[float] = None
    error: Optional[str] = None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(round((len(values) - 1) * p))
    return values[max(0, min(idx, len(values) - 1))]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load test the RAG chat API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--account", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--character-name", default=None)
    parser.add_argument("--chat-mode", default="online")
    parser.add_argument("--session-prefix", default="stress")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--query-file", default=None)
    return parser.parse_args()


def load_queries(path: Optional[str]) -> list[str]:
    if not path:
        return DEFAULT_QUERIES[:]
    with open(path, "r", encoding="utf-8") as f:
        items = [line.strip() for line in f if line.strip()]
    return items or DEFAULT_QUERIES[:]


def login(base_url: str, account: str, password: str, timeout: float) -> str:
    resp = requests.post(
        f"{base_url}/api/login",
        json={"account": account, "password": password},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("message") or "login failed")
    token = payload.get("token")
    if not token:
        raise RuntimeError("missing token from login response")
    return token


def fetch_character_name(base_url: str, token: str, timeout: float) -> str:
    resp = requests.get(
        f"{base_url}/api/characters",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    items = resp.json()
    if not items:
        raise RuntimeError("no characters returned by /api/characters")
    return items[0]["name"]


def build_payload(
    query: str,
    session_id: str,
    character_name: str,
    chat_mode: str,
) -> dict:
    return {
        "query": query,
        "session_id": session_id,
        "character_name": character_name,
        "chat_mode": chat_mode,
        "conversation_title": session_id,
    }


def run_chat_once(
    base_url: str,
    token: str,
    payload: dict,
    timeout: float,
) -> Result:
    start = time.perf_counter()
    try:
        resp = requests.post(
            f"{base_url}/api/rag/chat",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout,
        )
        latency = time.perf_counter() - start
        resp.raise_for_status()
        body = resp.json()
        if "response" not in body:
            return Result(False, latency, error="missing response field")
        return Result(True, latency)
    except Exception as exc:
        latency = time.perf_counter() - start
        return Result(False, latency, error=str(exc))


def run_stream_once(
    base_url: str,
    token: str,
    payload: dict,
    timeout: float,
) -> Result:
    start = time.perf_counter()
    first_chunk: Optional[float] = None
    try:
        with requests.post(
            f"{base_url}/api/rag/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            stream=True,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if line and first_chunk is None:
                    first_chunk = time.perf_counter() - start
                if line == "event: done":
                    break
        latency = time.perf_counter() - start
        return Result(True, latency, ttfb=first_chunk)
    except Exception as exc:
        latency = time.perf_counter() - start
        return Result(False, latency, ttfb=first_chunk, error=str(exc))


def run_worker(
    worker_id: int,
    base_url: str,
    token: str,
    character_name: str,
    chat_mode: str,
    session_prefix: str,
    queries: list[str],
    stream: bool,
    timeout: float,
    total_requests: int,
) -> list[Result]:
    results: list[Result] = []
    session_id = f"{session_prefix}-{worker_id}-{int(time.time())}"
    for i in range(total_requests):
        query = random.choice(queries)
        payload = build_payload(query, session_id, character_name, chat_mode)
        if stream:
            result = run_stream_once(base_url, token, payload, timeout)
        else:
            result = run_chat_once(base_url, token, payload, timeout)
        results.append(result)
    return results


def summarize(results: Iterable[Result]) -> None:
    results = list(results)
    latencies = [r.latency for r in results]
    ttfb_values = [r.ttfb for r in results if r.ttfb is not None]
    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    total = len(results)
    elapsed = sum(latencies)
    print(f"total={total} ok={ok_count} fail={fail_count}")
    print(f"avg_latency={statistics.mean(latencies):.4f}s" if latencies else "avg_latency=0")
    print(f"p50={percentile(latencies, 0.50):.4f}s")
    print(f"p95={percentile(latencies, 0.95):.4f}s")
    print(f"p99={percentile(latencies, 0.99):.4f}s")
    print(f"max={max(latencies):.4f}s" if latencies else "max=0")
    if ttfb_values:
        print(f"ttfb_p50={percentile(ttfb_values, 0.50):.4f}s")
        print(f"ttfb_p95={percentile(ttfb_values, 0.95):.4f}s")
    print(f"sum_latency={elapsed:.4f}s")


def main() -> int:
    args = parse_args()
    queries = load_queries(args.query_file)
    if not queries:
        print("No queries available.", file=sys.stderr)
        return 2

    token = login(args.base_url, args.account, args.password, args.timeout)
    character_name = args.character_name or fetch_character_name(
        args.base_url, token, args.timeout
    )

    total_requests = args.requests
    concurrency = max(1, args.concurrency)
    per_worker = total_requests // concurrency
    remainder = total_requests % concurrency

    start = time.perf_counter()
    all_results: list[Result] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for worker_id in range(concurrency):
            count = per_worker + (1 if worker_id < remainder else 0)
            if count <= 0:
                continue
            futures.append(
                pool.submit(
                    run_worker,
                    worker_id,
                    args.base_url,
                    token,
                    character_name,
                    args.chat_mode,
                    args.session_prefix,
                    queries,
                    args.stream,
                    args.timeout,
                    count,
                )
            )
        for future in as_completed(futures):
            all_results.extend(future.result())

    wall = time.perf_counter() - start
    summarize(all_results)
    print(f"wall_time={wall:.4f}s")
    print(f"rps={(len(all_results) / wall):.2f}" if wall > 0 else "rps=0")

    failures = [r for r in all_results if not r.ok]
    if failures:
        print("failures:")
        for item in failures[:10]:
            print(f"- latency={item.latency:.4f}s error={item.error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
