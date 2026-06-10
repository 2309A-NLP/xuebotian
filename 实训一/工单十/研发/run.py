from __future__ import annotations

from pathlib import Path

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    run_kwargs = {
        "app": "app.main:app",
        "host": settings.host,
        "port": settings.port,
        "reload": settings.debug,
    }
    if settings.debug:
        root_dir = Path(__file__).resolve().parent
        run_kwargs.update(
            {
                "reload_dirs": [
                    str(root_dir / "app"),
                    str(root_dir / "frontend"),
                ],
                "reload_excludes": [
                    "data",
                    "data/*",
                ],
            }
        )
    uvicorn.run(**run_kwargs)


if __name__ == "__main__":
    main()
