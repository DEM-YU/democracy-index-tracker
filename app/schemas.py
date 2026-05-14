"""Pydantic request/response schemas for Democracy Index Tracker."""

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared config mixin
# ---------------------------------------------------------------------------


class _OrmBase(BaseModel):
    """Enable ORM-mode for all subclasses so SQLAlchemy models map cleanly."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Payload required to register a new user."""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)


class UserResponse(_OrmBase):
    """Public representation of a user (never exposes hashed_password)."""

    id: int
    username: str
    is_admin: bool


class Token(BaseModel):
    """JWT bearer token returned after successful authentication."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Claims extracted from a decoded JWT."""

    username: str | None = None


# ---------------------------------------------------------------------------
# Data schemas
# ---------------------------------------------------------------------------


class DemocracyIndexResponse(_OrmBase):
    """Annual V-Dem electoral democracy score (0–1) for a country."""

    year: int
    democracy_index: float


class CountryBase(BaseModel):
    """Minimal country fields shared across create and response schemas."""

    name: str = Field(..., min_length=1, max_length=128)
    region: str = Field(..., min_length=1, max_length=128)


class CountryResponse(_OrmBase, CountryBase):
    """Country record as returned by list endpoints."""

    id: int


class CountryDetailResponse(CountryResponse):
    """Country record with full historical index data."""

    history: list[DemocracyIndexResponse] = []
