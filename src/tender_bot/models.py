"""Pydantic models for tender data and user settings."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TenderItem(BaseModel):
    """A single tender/auction entry parsed from a source website."""

    source: str = Field(description="Source website: 'goszakupki' or 'icetrade'")
    tender_id: str = Field(description="Unique tender identifier from the source")
    title: str = Field(description="Tender title / description")
    url: str = Field(description="Direct URL to the tender page")
    organization: str = Field(default="", description="Customer / organization name")
    max_cost: str = Field(default="Не указана", description="Max estimated cost")
    publish_period: str = Field(default="", description="Publish date or period")
    submission_deadline: str = Field(default="", description="Application deadline")
    execution_period: str = Field(default="", description="Execution or delivery period")
    status: str = Field(default="", description="Current tender status")
    tender_type: str = Field(default="", description="Type of procurement procedure")
    found_at: datetime = Field(default_factory=datetime.now)


class UserSettings(BaseModel):
    """Per-user notification settings stored in the database."""

    chat_id: int
    keywords: list[str] = Field(default_factory=list)
    enabled: bool = Field(default=True)
