import json
import sys
import zipfile
from pathlib import Path

# Tool configuration that Chrome does not need.
LEFT_OUT = {"biome.jsonc"}


def package(source: Path, destination: Path) -> Path:
    match json.loads((source / "manifest.json").read_text(encoding="utf-8")):
        case {"version": str(version)}:
            archive = destination / f"whadio-extension-{version}.zip"
        case _:
            sys.exit("manifest.json has no version")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.name not in LEFT_OUT:
                bundle.write(path, path.relative_to(source))
    return archive


def main() -> None:
    sys.stdout.write(f"{package(Path(sys.argv[1]), Path(sys.argv[2]))}\n")


if __name__ == "__main__":
    main()
