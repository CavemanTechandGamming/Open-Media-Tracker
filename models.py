"""SQLAlchemy models for media libraries, episodes, and application configuration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_name: Mapped[str] = mapped_column(String(512), nullable=False)
    folder_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    folder_mtime: Mapped[float] = mapped_column(Float, nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)  # tv | movie

    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tvdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # TMDB status strings e.g. "Ended", "Returning Series", "Released"
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    poster_local: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    total_episodes_api: Mapped[int] = mapped_column(Integer, default=0)
    episodes_present_local: Mapped[int] = mapped_column(Integer, default=0)

    last_api_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    episodes: Mapped[list["Episode"]] = relationship(
        "Episode",
        back_populates="media",
        cascade="all, delete-orphan",
    )


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (Index("ix_episodes_media_exists", "media_id", "exists_locally"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    exists_locally: Mapped[bool] = mapped_column(Boolean, default=False)

    media: Mapped["Media"] = relationship("Media", back_populates="episodes")


class Config(Base):
    """Key/value settings persisted in SQLite (overrides env defaults when set)."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
