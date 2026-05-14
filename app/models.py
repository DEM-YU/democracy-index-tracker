"""SQLAlchemy ORM models for Democracy Index Tracker."""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# ---------------------------------------------------------------------------
# Many-to-many association table: users <-> countries (watchlist)
# ---------------------------------------------------------------------------

user_watchlist = Table(
    "user_watchlist",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "country_id",
        Integer,
        ForeignKey("countries.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(Base):
    """Application user who can authenticate and maintain a country watchlist."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    watchlist: Mapped[list["Country"]] = relationship(
        "Country",
        secondary=user_watchlist,
        back_populates="watchers",
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------


class Country(Base):
    """A sovereign country tracked by the democracy index dataset."""

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    region: Mapped[str] = mapped_column(String, index=True, nullable=False)

    history: Mapped[list["DemocracyIndex"]] = relationship(
        "DemocracyIndex",
        back_populates="country",
        cascade="all, delete-orphan",
        order_by="DemocracyIndex.year",
        lazy="selectin",
    )

    watchers: Mapped[list[User]] = relationship(
        "User",
        secondary=user_watchlist,
        back_populates="watchlist",
    )


# ---------------------------------------------------------------------------
# DemocracyIndex
# ---------------------------------------------------------------------------


class DemocracyIndex(Base):
    """Annual V-Dem electoral democracy score (0–1) for a single country."""

    __tablename__ = "democracy_indices"

    __table_args__ = (
        UniqueConstraint("country_id", "year", name="uq_country_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    country_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("countries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    democracy_index: Mapped[float] = mapped_column(Float, nullable=False)

    country: Mapped["Country"] = relationship("Country", back_populates="history")
