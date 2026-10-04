import json
from pathlib import Path
from typing import Final

from fastapi import FastAPI

OUTPUT_DIR: Final = Path(__file__).resolve().parents[2] / "docs" / "api"
OUTPUT_FILE: Final = OUTPUT_DIR / "openapi-generated.json"


def render_openapi_json(app: FastAPI) -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def export_openapi(app: FastAPI, path: Path = OUTPUT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_openapi_json(app), encoding="utf-8")
    return path


if __name__ == "__main__":
    from .app import create_app

    print(f"Wrote {export_openapi(create_app(include_mcp=False))}")
