import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_DIR = REPO_ROOT / "docs" / "api"
JSON_PATH = SPEC_DIR / "openapi-generated.json"
YAML_PATH = SPEC_DIR / "openapi-generated.yaml"


def validate_spec_structure(spec: dict[str, Any]) -> None:
    if not spec.get("openapi", "").startswith("3."):
        raise ValueError(f"Invalid OpenAPI version: {spec.get('openapi')}")

    info = spec.get("info", {})
    if not info.get("title") or not info.get("version"):
        raise ValueError("Missing OpenAPI info.title or info.version")

    paths = spec.get("paths", {})
    if not paths:
        raise ValueError("OpenAPI specification must contain path definitions")

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            if not isinstance(operation, dict):
                continue
            if "responses" not in operation or not operation["responses"]:
                raise ValueError(f"Endpoint {method.upper()} {path} missing responses")
            if not operation.get("summary") and not operation.get("description"):
                raise ValueError(
                    f"Endpoint {method.upper()} {path} missing summary/description documentation"
                )


def main() -> None:
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"{JSON_PATH} does not exist. Run openapi_export first.")
    if not YAML_PATH.exists():
        raise FileNotFoundError(f"{YAML_PATH} does not exist. Run openapi_export first.")

    with JSON_PATH.open("r", encoding="utf-8") as f:
        json_spec = json.load(f)

    validate_spec_structure(json_spec)

    try:
        import yaml

        with YAML_PATH.open("r", encoding="utf-8") as f:
            yaml_spec = yaml.safe_load(f)

        validate_spec_structure(yaml_spec)

        if json_spec != yaml_spec:
            raise ValueError(
                "JSON and YAML OpenAPI specifications are out of sync! "
                "Ensure both are generated using the export script."
            )
        print("  YAML and JSON representations match exactly.")
    except ImportError:
        print("  [Note] pyyaml not installed in environment; validated JSON spec only.")

    path_count = len(json_spec.get("paths", {}))
    op_count = sum(
        1
        for p in json_spec.get("paths", {}).values()
        if isinstance(p, dict)
        for m in p.keys()
        if m.lower() in {"get", "post", "put", "patch", "delete"}
    )
    print(
        f"OK: OpenAPI spec is valid ({path_count} paths, {op_count} operations, OpenAPI {json_spec['openapi']})"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
