import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose Milvus collection availability and recovery state."
    )
    parser.add_argument(
        "--uri",
        default=None,
        help="Milvus URI. Defaults to app.core.config.MILVUS_URI",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Milvus DB name. Defaults to app.core.config.MILVUS_DB_NAME",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Collection name. Defaults to app.core.config.MILVUS_COLLECTION_NAME",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="How many rows to query as a smoke test.",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=5,
        help="Retry count when collection is recovering.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between retries.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for load/query steps before treating them as stuck.",
    )
    return parser.parse_args()


def load_config() -> Tuple[str, str, str]:
    from app.core.config import MILVUS_COLLECTION_NAME, MILVUS_DB_NAME, MILVUS_URI

    return MILVUS_URI, MILVUS_DB_NAME, MILVUS_COLLECTION_NAME


def build_client(uri: str, db_name: str):
    from pymilvus import MilvusClient

    return MilvusClient(uri=uri, db_name=db_name)


def safe_call(label: str, fn):
    try:
        return True, fn(), None
    except Exception as exc:
        return False, None, exc


def _worker_run(step: str, uri: str, db_name: str, collection_name: str, limit: int, queue: mp.Queue) -> None:
    try:
        client = build_client(uri, db_name)
        if step == "load_collection":
            result = client.load_collection(collection_name)
        elif step == "query":
            result = client.query(
                collection_name=collection_name,
                filter="id >= 0",
                output_fields=["id"],
                limit=max(1, limit),
            )
        else:
            raise ValueError(f"unknown step: {step}")
        queue.put(("ok", result))
    except Exception as exc:
        queue.put(("err", f"{type(exc).__name__}: {exc}"))


def timed_step(
    step: str,
    uri: str,
    db_name: str,
    collection_name: str,
    limit: int,
    timeout: float,
):
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_worker_run,
        args=(step, uri, db_name, collection_name, limit, queue),
        daemon=True,
    )
    proc.start()
    proc.join(max(0.1, timeout))
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return False, None, TimeoutError(f"{step} timed out after {timeout:.1f}s")
    if queue.empty():
        return False, None, RuntimeError(f"{step} finished without result")
    status, payload = queue.get_nowait()
    if status == "ok":
        return True, payload, None
    return False, None, RuntimeError(payload)


def format_exc(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def try_load_collection(uri: str, db_name: str, collection_name: str) -> Optional[Exception]:
    ok, _, exc = timed_step(
        "load_collection",
        uri=uri,
        db_name=db_name,
        collection_name=collection_name,
        limit=1,
        timeout=20.0,
    )
    return None if ok else exc


def main() -> int:
    args = parse_args()
    default_uri, default_db, default_collection = load_config()
    uri = args.uri or default_uri
    db_name = args.db or default_db
    collection_name = args.collection or default_collection

    print(f"uri={uri}")
    print(f"db={db_name}")
    print(f"collection={collection_name}")

    client = build_client(uri, db_name)

    ok, collections, exc = safe_call("list_collections", client.list_collections)
    if not ok:
        print(f"list_collections failed: {format_exc(exc)}")
        return 2
    print(f"collections={collections}")

    ok, has_collection, exc = safe_call("has_collection", lambda: client.has_collection(collection_name))
    if not ok:
        print(f"has_collection failed: {format_exc(exc)}")
        return 2
    print(f"has_collection={has_collection}")

    ok, details, exc = safe_call(
        "describe_collection", lambda: client.describe_collection(collection_name=collection_name)
    )
    if ok:
        print(f"describe_collection.fields={len((details or {}).get('fields', []))}")
    else:
        print(f"describe_collection failed: {format_exc(exc)}")

    print("load_collection: start")
    load_exc = try_load_collection(uri, db_name, collection_name)
    if load_exc is None:
        print("load_collection: ok_or_not_supported")
    else:
        print(f"load_collection: failed: {format_exc(load_exc)}")

    for attempt in range(1, max(1, args.retry) + 1):
        print(f"query attempt {attempt}: start")
        ok, rows, exc = timed_step(
            "query",
            uri=uri,
            db_name=db_name,
            collection_name=collection_name,
            limit=args.limit,
            timeout=max(0.1, args.timeout),
        )
        if ok:
            print(f"query=ok rows={len(rows or [])}")
            if rows:
                print(f"first_row={rows[0]}")
            return 0

        message = format_exc(exc)
        print(f"query attempt {attempt} failed: {message}")
        if attempt < args.retry:
            time.sleep(max(0.0, args.interval))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
