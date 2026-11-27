import sys
from collections.abc import Collection

DOCUMENTATION_FOLDERS = ("docs/", "Labs/", ".agents/", ".github/ISSUE_TEMPLATE/")


def is_documentation(path: str) -> bool:
    top_level_markdown = "/" not in path and path.endswith(".md")
    return top_level_markdown or path.startswith(DOCUMENTATION_FOLDERS)


def touches_code(paths: Collection[str]) -> bool:
    """An empty list counts as code: when nothing is known to have changed, CI runs everything."""
    return not paths or not all(is_documentation(path) for path in paths)


def main() -> None:
    paths = [line for line in sys.stdin.read().splitlines() if line]
    sys.stdout.write("true\n" if touches_code(paths) else "false\n")


if __name__ == "__main__":
    main()
