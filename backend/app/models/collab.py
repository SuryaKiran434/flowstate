"""
Collaborative Arc Session ORM Models — Flowstate
--------------------------------------------------
Two tables:
  - CollabSession:     A shared arc session created by a host user
  - CollabParticipant: Each user's emotional state contribution to a collab session
"""

import uuid
from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, func, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base


class CollabSession(Base):
    __tablename__ = "collab_sessions"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invite_code      = Column(String(8), unique=True, nullable=False, index=True)
    target_emotion   = Column(String(50), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=30)
    # open | generating | ready
    status           = Column(String(20), nullable=False, default="open", index=True)
    # Computed centroid source emotion after aggregation
    aggregated_source = Column(String(50), nullable=True)
    # Full arc result JSON stored after generation
    arc_json         = Column(JSON, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


class CollabParticipant(Base):
    __tablename__ = "collab_participants"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id     = Column(UUID(as_uuid=True), ForeignKey("collab_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_emotion = Column(String(50), nullable=False)
    joined_at      = Column(DateTime(timezone=True), server_default=func.now())
