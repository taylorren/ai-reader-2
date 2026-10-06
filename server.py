"""FastAPI server for ai-reader-2.

Scaffold: the app assembles and every router is registered. The routers are
empty until their phase lands — see SPEC.md for what each one will own.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent


def load_env():
    """Load environment variables from .env, as ai-reader does."""
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
                os.environ[key.strip()] = value.strip()
    print(f"✓ Loaded Ollama endpoint: {os.getenv('OLLAMA_BASE_URL', 'Not set')}")


load_env()

app = FastAPI(title="ai-reader-2")
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
