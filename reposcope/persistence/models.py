from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey,
    Index, Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONB_ = JSONB().with_variant(JSON(), "sqlite")
UUID_ = UUID(as_uuid=True).with_variant(String(36), "sqlite")


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID_, primary_key=True, default=uuid.uuid4)


class Repo(Base):
    __tablename__ = "repos"
    id: Mapped[uuid.UUID] = _pk()
    url: Mapped[str] = mapped_column(Text, unique=True)
    host: Mapped[str] = mapped_column(String(64), default="github.com")
    owner: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    default_branch: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    """One pass over one commit. All evidence hangs off a run, so re-analysing
    a repo never mutates the numbers you already published."""

    __tablename__ = "analysis_runs"
    id: Mapped[uuid.UUID] = _pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    # queued|cloning|parsing|classifying|analyzing|summarizing|complete|failed
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[dict] = mapped_column(JSONB_, default=dict)
    config_snapshot: Mapped[dict] = mapped_column(JSONB_, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB_, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repo: Mapped[Repo] = relationship()

    __table_args__ = (Index("ix_runs_repo_commit", "repo_id", "commit_sha"),)


class File(Base):
    __tablename__ = "files"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    loc: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(32))
    # Graph-derived importance; populated after the graph is built.
    centrality: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("run_id", "path", name="uq_files_run_path"),
        Index("ix_files_run_included", "run_id", "included"),
    )


class Symbol(Base):
    __tablename__ = "symbols"
    id: Mapped[uuid.UUID] = _pk()
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    # function|method|class|constant|type|variable
    kind: Mapped[str] = mapped_column(String(24))
    qualified_name: Mapped[str | None] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    is_exported: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_symbols_file_name", "file_id", "name"),)


class DepEdge(Base):
    """The dependency graph. Deterministic by construction — no model output
    ever writes here. `reliability` separates AST-exact edges from inferred
    ones so citation verification can require `exact`."""

    __tablename__ = "dep_edges"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    src_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    src_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL")
    )
    src_line: Mapped[int] = mapped_column(Integer)
    dst_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE")
    )
    dst_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL")
    )
    dst_external: Mapped[str | None] = mapped_column(Text)
    # import|reexport|dynamic_import|call|inherit|instantiate
    kind: Mapped[str] = mapped_column(String(20))
    # resolved|external|unresolved
    resolution: Mapped[str] = mapped_column(String(16))
    # exact|heuristic|ambiguous
    reliability: Mapped[str] = mapped_column(String(12), default="exact")
    raw_specifier: Mapped[str | None] = mapped_column(Text)
    resolver_evidence: Mapped[dict] = mapped_column(JSONB_, default=dict)
    resolver_version: Mapped[str] = mapped_column(String(32), default="0.1.0")

    __table_args__ = (
        CheckConstraint(
            "(dst_file_id IS NOT NULL) <> (dst_external IS NOT NULL)",
            name="ck_edge_target_exclusive",
        ),
        Index("ix_edges_src", "run_id", "src_file_id"),
        Index("ix_edges_dst", "run_id", "dst_file_id"),
        Index("ix_edges_kind_rel", "run_id", "kind", "reliability"),
    )


class Module(Base):
    __tablename__ = "modules"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # directory|graph_cluster|jev
    derivation: Mapped[str] = mapped_column(String(20))


class FileModule(Base):
    __tablename__ = "file_modules"
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)


class Decision(Base):
    """One question, one file, one provider. Jev and the comparison LLM write
    to the same table so the benchmark is a self-join, not a reconciliation."""

    __tablename__ = "decisions"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    question_key: Mapped[str] = mapped_column(String(64))
    question_version: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(16))  # jev|llm
    model: Mapped[str] = mapped_column(String(64))
    answer_type: Mapped[str] = mapped_column(String(12))  # noul|choice|score

    state_hash: Mapped[str] = mapped_column(String(64))
    state_snapshot: Mapped[dict] = mapped_column(JSONB_, default=dict)

    answer: Mapped[dict] = mapped_column(JSONB_)            # {"choice": "route"} etc.
    probabilities: Mapped[dict] = mapped_column(JSONB_, default=dict)
    # NULL for noul answers: noul carries no separate confidence field.
    confidence: Mapped[float | None] = mapped_column(Float)
    # Uniform 0-1 certainty derived per answer type, so routing is comparable.
    certainty: Mapped[float] = mapped_column(Float)

    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 8))
    request_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_id", "file_id", "question_key", "provider", "model", "state_hash",
            name="uq_decision_identity",
        ),
        Index("ix_decisions_run_provider", "run_id", "provider", "question_key"),
    )


class RoutingEvent(Base):
    __tablename__ = "routing_events"
    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), unique=True
    )
    threshold_value: Mapped[float] = mapped_column(Float)
    threshold_source: Mapped[str] = mapped_column(String(32))  # default|config|override
    # auto_accept|flag_for_review|escalate_to_llm|reject
    action: Mapped[str] = mapped_column(String(24))
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolved_label: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoldLabel(Base):
    """Hand-labelled ground truth. Without this the Jev-vs-LLM comparison
    measures agreement, not accuracy."""

    __tablename__ = "gold_labels"
    id: Mapped[uuid.UUID] = _pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    commit_sha: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(Text)
    labeled_by: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("repo_id", "commit_sha", "path", "question_key", name="uq_gold"),
    )


class DeepAnalysis(Base):
    __tablename__ = "deep_analyses"
    id: Mapped[uuid.UUID] = _pk()
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Claim(Base):
    """An assertion in a deep analysis, pinned to a location. `verified` is
    what makes 'evidence-backed' true: unverified claims never reach the UI."""

    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = _pk()
    deep_analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deep_analyses.id", ondelete="CASCADE")
    )
    # does|depends_on|depended_by|breaks_if
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    evidence_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE")
    )
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    supporting_edge_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dep_edges.id", ondelete="SET NULL")
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # file_exists|line_exists|edge_match|none
    verification_method: Mapped[str | None] = mapped_column(String(24))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class RepoSummary(Base):
    __tablename__ = "repo_summaries"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True
    )
    overview: Mapped[str] = mapped_column(Text)
    entry_points: Mapped[list] = mapped_column(JSONB_, default=list)
    data_flow: Mapped[str | None] = mapped_column(Text)
    module_boundaries: Mapped[list] = mapped_column(JSONB_, default=list)
    key_files: Mapped[list] = mapped_column(JSONB_, default=list)
    model: Mapped[str | None] = mapped_column(String(64))
