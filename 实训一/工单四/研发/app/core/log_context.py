from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
doc_id_var: ContextVar[str] = ContextVar("doc_id", default="-")


def get_request_id() -> str:
    return request_id_var.get()


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    token = request_id_var.set(request_id or "-")
    try:
        yield
    finally:
        request_id_var.reset(token)


@contextmanager
def bind_doc_id(doc_id: str) -> Iterator[None]:
    token = doc_id_var.set(doc_id or "-")
    try:
        yield
    finally:
        doc_id_var.reset(token)
