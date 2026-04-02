"""
Session ORM Models — Flowstate
--------------------------------
Two tables:
  - Session:      A listening session generated from a mood arc request
  - SessionTrack: Ordered tracks within a session, with play/skip telemetry
"""

import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    func,
    ARRAY,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_emotion = Column(String(50), nullable=False)
    target_emotion = Column(String(50), nullable=False)
    duration_mins = Column(Integer, nullable=False)
    # generated | active | completed | abandoned
    status = Column(String(20), nullable=False, default="generated", index=True)
    arc_path = Column(ARRAY(Text), nullable=True)  # ordered emotion node names
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class SessionTrack(Base):
    __tablename__ = "session_tracks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id = Column(String(50), ForeignKey("tracks.id"), nullable=False)
    position = Column(Integer, nullable=False)
    emotion_label = Column(String(50), nullable=True)
    arc_segment = Column(Integer, nullable=True)
    played = Column(Boolean, nullable=False, default=False)
    skipped = Column(Boolean, nullable=False, default=False)
    played_at = Column(DateTime(timezone=True), nullable=True)
