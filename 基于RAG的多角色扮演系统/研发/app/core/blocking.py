import asyncio
from typing import Any, Callable, TypeVar


T = TypeVar("T")


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await asyncio.to_thread(func, *args, **kwargs)
