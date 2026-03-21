"""
ArcTemplate ORM Model — Flowstate
------------------------------------
Stores a shareable arc template: the emotional skeleton (source, path, target,
duration) that any user can remix against their own track library.
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from app.db.session import Base


class ArcTemplate(Base):
    __tablename__ = "arc_templates"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name   = Column(String(200), nullable=False)
    description    = Column(Text, nullable=True)
    source_emotion = Column(String(50), nullable=False)
    target_emotion = Column(String(50), nullable=False)
    arc_path       = Column(ARRAY(Text), nullable=False)  # ordered emotion labels
    duration_mins  = Column(Integer, nullable=False)
    remix_count    = Column(Integer, nullable=False, default=0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
