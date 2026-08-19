import re
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def local_markdown_links(text):
    for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        parsed = urlparse(target)
        if parsed.scheme or target.startswith("#"):
            continue
        yield unquote(parsed.path or target)


def main():
    missing = []
    for target in local_markdown_links(README.read_text(encoding="utf-8")):
        if not (ROOT / target).exists():
            missing.append(target)
    if missing:
        raise AssertionError(f"README local links point to missing files: {missing}")
    print("test_readme_links: OK")


if __name__ == "__main__":
    main()
