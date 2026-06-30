from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cost_detective.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    analyses = relationship("Analysis", back_populates="user")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    region = Column(String(64), nullable=False)
    scan_target = Column(String(255), nullable=False, default="whole-region")
    resources_scanned = Column(Integer, nullable=False, default=0)
    issues_found = Column(Integer, nullable=False, default=0)
    estimated_savings = Column(Text, nullable=False, default="Unknown")
    analysis_result = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="queued")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="analyses")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).first()


def create_user(db: Session, email: str, password_hash: str) -> User:
    user = User(email=email.lower(), password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_analysis(db: Session, user_id: int, region: str, resource_group: str | None) -> Analysis:
    analysis = Analysis(
        user_id=user_id,
        region=region,
        scan_target=resource_group or "whole-region",
        status="queued",
        analysis_result={},
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def complete_analysis(
    db: Session,
    analysis_id: int,
    result: dict[str, Any],
    resources_scanned: int,
    issues_found: int,
    estimated_savings: str,
    status: str = "completed",
) -> Analysis | None:
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        return None
    analysis.analysis_result = result
    analysis.resources_scanned = resources_scanned
    analysis.issues_found = issues_found
    analysis.estimated_savings = estimated_savings
    analysis.status = status
    db.commit()
    db.refresh(analysis)
    return analysis


def fail_analysis(db: Session, analysis_id: int, message: str) -> Analysis | None:
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        return None
    analysis.status = "failed"
    analysis.analysis_result = {"error": message, "reason": message}
    db.commit()
    db.refresh(analysis)
    return analysis


def cancel_analysis(db: Session, analysis_id: int, message: str) -> Analysis | None:
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        return None
    analysis.status = "cancelled"
    analysis.analysis_result = {"error": message, "reason": message}
    db.commit()
    db.refresh(analysis)
    return analysis


def cleanup_stale_jobs(db: Session) -> int:
    stale_analyses = db.query(Analysis).filter(Analysis.status.in_(["queued", "running"])).all()
    count = len(stale_analyses)
    for analysis in stale_analyses:
        analysis.status = "interrupted"
        analysis.analysis_result = {"error": "Analysis was interrupted by server restart.", "reason": "Analysis was interrupted by server restart."}
    if count > 0:
        db.commit()
    return count


def cleanup_history_retention(db: Session) -> int:
    if not _env_bool("ANALYSIS_HISTORY_RETENTION_ENABLED", False):
        return 0

    max_records = _env_int_optional("ANALYSIS_HISTORY_MAX_RECORDS")
    retention_days = _env_int_optional("ANALYSIS_HISTORY_RETENTION_DAYS")
    if max_records is None and retention_days is None:
        return 0

    deleted_count = 0
    users = db.query(User).all()
    for user in users:
        if max_records is not None and max_records >= 0:
            keep_ids = [
                row.id
                for row in db.query(Analysis.id)
                .filter(Analysis.user_id == user.id)
                .order_by(Analysis.created_at.desc())
                .limit(max_records)
                .all()
            ]
            query = db.query(Analysis).filter(Analysis.user_id == user.id)
            if keep_ids:
                query = query.filter(Analysis.id.notin_(keep_ids))
            for analysis in query.all():
                db.delete(analysis)
                deleted_count += 1

        if retention_days is not None and retention_days >= 0:
            cutoff = utcnow() - timedelta(days=retention_days)
            stale = (
                db.query(Analysis)
                .filter(Analysis.user_id == user.id)
                .filter(Analysis.created_at < cutoff)
                .all()
            )
            for analysis in stale:
                db.delete(analysis)
                deleted_count += 1

    if deleted_count > 0:
        db.commit()
    return deleted_count


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int_optional(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def serialize_analysis(analysis: Analysis) -> dict[str, Any]:
    return {
        "id": analysis.id,
        "user_id": analysis.user_id,
        "region": analysis.region,
        "scan_target": analysis.scan_target,
        "resources_scanned": analysis.resources_scanned,
        "issues_found": analysis.issues_found,
        "estimated_savings": analysis.estimated_savings,
        "analysis_result": analysis.analysis_result,
        "status": analysis.status,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }