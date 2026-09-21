"""Clone a public GitHub repository into a scratch directory.

Hostile input is assumed: the URL comes from a text box on a public page. We
parse it into owner/name ourselves and rebuild the clone URL rather than
handing user text to git, which otherwise accepts file://, ssh:// and
--upload-pack= style arguments.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

GITHUB_HOSTS = {"github.com", "www.github.com"}

# GitHub's own rules: 1-39 chars for owner, and repo names allow . _ -
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<name>[A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?/?$"
)


class CloneError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class Checkout:
    ref: RepoRef
    path: Path
    commit_sha: str
    default_branch: str


def parse_url(url: str) -> RepoRef:
    cleaned = url.strip().split("?")[0].split("#")[0]
    match = _URL_RE.match(cleaned)
    if not match:
        raise CloneError(f"Not a GitHub repository URL: {url!r}")
    name = match.group("name")
    if name in {".", ".."}:
        raise CloneError(f"Invalid repository name: {name!r}")
    return RepoRef(owner=match.group("owner"), name=name)


def _git(args: list[str], cwd: Path | None, timeout: int) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        # Block credential prompts and any interactive hang.
        env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "PATH": "/usr/bin:/bin"},
    )
    if proc.returncode != 0:
        raise CloneError(proc.stderr.strip()[:500] or f"git {args[0]} failed")
    return proc.stdout.strip()


def clone(url: str, workdir: Path, *, timeout_s: int = 300, ref: str | None = None) -> Checkout:
    """Shallow-clone the repo. Caller owns cleanup via `discard`."""
    repo = parse_url(url)
    workdir.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix=f"{repo.owner}__{repo.name}__", dir=workdir))

    args = ["clone", "--depth", "1", "--single-branch", "--no-tags"]
    if ref:
        args += ["--branch", ref]
    args += ["--", repo.clone_url, str(dest)]

    try:
        _git(args, cwd=None, timeout=timeout_s)
        sha = _git(["rev-parse", "HEAD"], cwd=dest, timeout=30)
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest, timeout=30)
    except subprocess.TimeoutExpired as exc:
        discard(dest)
        raise CloneError(f"Clone timed out after {timeout_s}s") from exc
    except CloneError:
        discard(dest)
        raise

    return Checkout(ref=repo, path=dest, commit_sha=sha, default_branch=branch)


def discard(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def directory_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())
    return total / (1024 * 1024)
