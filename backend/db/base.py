"""SQLAlchemy declarative base and shared metadata for trading database models."""

from __future__ import annotations

import logging

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

metadata = MetaData()


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    metadata = metadata
