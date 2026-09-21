from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from reposcope.config import settings
from reposcope.ingest import clone as clone_mod
from reposcope.ingest.walk import WalkedFile, summarize, walk
from reposcope.persistence.models import AnalysisRun, File, Repo


@dataclass
class IngestResult:
    run_id: uuid.UUID
    checkout: clone_mod.Checkout
    files: list[WalkedFile]
    coverage: dict


def get_or_create_repo(session: Session, url: str) -> Repo:
    ref = clone_mod.parse_url(url)
    canonical = f"https://github.com/{ref.owner}/{ref.name}"
    repo = session.scalar(select(Repo).where(Repo.url == canonical))
    if repo is None:
        repo = Repo(url=canonical, owner=ref.owner, name=ref.name)
        session.add(repo)
        session.flush()
    return repo


def start_run(session: Session, url: str) -> AnalysisRun:
    repo = get_or_create_repo(session, url)
    run = AnalysisRun(repo_id=repo.id, status="queued", config_snapshot=settings.snapshot())
    session.add(run)
    session.flush()
    return run


def _set_stage(session: Session, run: AnalysisRun, stage: str, **progress) -> None:
    run.status = stage
    run.progress = {"stage": stage, **progress}
    session.flush()


def ingest(session: Session, run: AnalysisRun, url: str, ref: str | None = None) -> IngestResult:
    """Clone, walk, and persist one row per file. Leaves the checkout on disk;
    the graph stage needs it. Caller calls clone_mod.discard when done."""
    _set_stage(session, run, "cloning")

    checkout = clone_mod.clone(
        url, Path(settings.workdir), timeout_s=settings.clone_timeout_s, ref=ref
    )

    size_mb = clone_mod.directory_size_mb(checkout.path)
    if size_mb > settings.max_repo_mb:
        clone_mod.discard(checkout.path)
        raise clone_mod.CloneError(
            f"Repository is {size_mb:.0f} MB, over the {settings.max_repo_mb} MB limit"
        )

    run.commit_sha = checkout.commit_sha
    repo = session.get(Repo, run.repo_id)
    if repo and not repo.default_branch:
        repo.default_branch = checkout.default_branch

    _set_stage(session, run, "parsing", files_done=0, files_total=None)

    files = list(walk(checkout.path, max_file_bytes=settings.max_file_bytes))
    session.add_all(
        [
            File(
                run_id=run.id,
                path=f.rel_path,
                language=f.language,
                size_bytes=f.size_bytes,
                loc=f.loc,
                content_hash=f.content_hash,
                included=f.included,
                exclusion_reason=f.exclusion_reason.value if f.exclusion_reason else None,
            )
            for f in files
        ]
    )

    coverage = summarize(files)
    run.coverage = coverage
    run.progress = {
        "stage": "parsing",
        "files_done": coverage["files_included"],
        "files_total": coverage["files_total"],
    }
    session.flush()

    return IngestResult(run_id=run.id, checkout=checkout, files=files, coverage=coverage)


def fail_run(session: Session, run: AnalysisRun, message: str) -> None:
    run.status = "failed"
    run.error = message[:2000]
    run.finished_at = datetime.now(timezone.utc)
    session.flush()
