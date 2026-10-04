import json
from pathlib import Path
from typing import Final

import yaml
from fastapi import FastAPI

OUTPUT_DIR: Final = Path("docs/api")
OUTPUT_JSON: Final = OUTPUT_DIR / "openapi-generated.json"
OUTPUT_YAML: Final = OUTPUT_DIR / "openapi-generated.yaml"


class _BlockStyleDumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_BlockStyleDumper.add_representer(str, _represent_str)


def render_openapi_json(app: FastAPI) -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def render_openapi_yaml(app: FastAPI) -> str:
    return yaml.dump(
        app.openapi(),
        Dumper=_BlockStyleDumper,
        sort_keys=False,
        allow_unicode=True,
    )


def export_openapi(app: FastAPI, directory: Path = OUTPUT_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = [directory / OUTPUT_YAML.name, directory / OUTPUT_JSON.name]
    written[0].write_text(render_openapi_yaml(app), encoding="utf-8")
    written[1].write_text(render_openapi_json(app), encoding="utf-8")
    return written


if __name__ == "__main__":
    from .app import create_app

    for path in export_openapi(create_app()):
        print(f"Wrote {path}")
