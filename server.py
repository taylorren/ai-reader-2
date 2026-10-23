"""FastAPI server for ai-reader-2.

The app assembles here: the library, reader, highlights, AI and settings routers
are all registered and live. `load_env()` reads `.env` before the app is built —
without overriding a variable that is already set, so an environment set for real
wins (see `load_env`).
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent


def load_env():
    """Load environment variables from .env, without overriding the real ones.

    `setdefault`, not assignment: `READER_PORT=9000 uv run server.py`, a systemd
    unit or a container's environment is an instruction, and `.env` used to
    silently replace it with whatever it said — which bites exactly when someone
    is trying to change something (REVIEW P2-7). Surrounding quotes are stripped,
    because a hand-written .env usually quotes its values.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        print("⚠ No .env file — AI features will not work.")
        return

    print("Loading .env file...")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    print(f"✓ Loaded Ollama endpoint: {os.getenv('OLLAMA_BASE_URL', 'Not set')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Release the AI client when the app stops.

    It is shared for the app's lifetime (one pool, one TLS context), so it is
    not closed per request — the loop that owns it is the one that closes it
    (REVIEW P3-9).
    """
    yield
    from routers import get_ai_service

    await get_ai_service().aclose()


load_env()

app = FastAPI(title="ai-reader-2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Register routers: each owns one area of the route table in SPEC.md.
from routers.ai import router as ai_router  # noqa: E402
from routers.highlights import router as highlights_router  # noqa: E402
from routers.library import router as library_router  # noqa: E402
from routers.reader import router as reader_router  # noqa: E402
from routers.settings import router as settings_router  # noqa: E402

app.include_router(library_router)
app.include_router(reader_router)
app.include_router(highlights_router)
app.include_router(ai_router)
app.include_router(settings_router)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("READER_HOST", "0.0.0.0")
    port = int(os.getenv("READER_PORT", "8123"))
    print(f"Starting server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
