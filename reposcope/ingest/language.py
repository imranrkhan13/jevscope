"""Map a file to a language.

v1 parses Python and TypeScript/JavaScript. Everything else is recorded with
its language so the repo-level summary can say what it didn't read, but it gets
no symbols and no edges.
"""

from __future__ import annotations

from pathlib import PurePosixPath

PARSEABLE = frozenset({"python", "typescript", "javascript"})

EXT_MAP: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".java": "java", ".kt": "kotlin",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".php": "php", ".swift": "swift", ".scala": "scala",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".html": "html", ".css": "css", ".scss": "scss",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".dockerfile": "dockerfile", ".tf": "terraform", ".proto": "protobuf",
}

FILENAME_MAP: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
    "Justfile": "just",
    ".gitignore": "text",
    ".env.example": "dotenv",
}

SHEBANG_MAP: tuple[tuple[str, str], ...] = (
    ("python", "python"),
    ("node", "javascript"),
    ("bash", "shell"),
    ("sh", "shell"),
    ("ruby", "ruby"),
)


def detect(rel_path: str, head: bytes = b"") -> str | None:
    name = PurePosixPath(rel_path).name

    if name in FILENAME_MAP:
        return FILENAME_MAP[name]
    if name.startswith("Dockerfile"):
        return "dockerfile"

    suffix = PurePosixPath(name).suffix.lower()
    if suffix in EXT_MAP:
        return EXT_MAP[suffix]

    if head.startswith(b"#!"):
        first = head.split(b"\n", 1)[0].decode("utf-8", "replace").lower()
        for needle, lang in SHEBANG_MAP:
            if needle in first:
                return lang

    return None


def is_parseable(language: str | None) -> bool:
    return language in PARSEABLE
