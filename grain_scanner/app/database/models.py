"""SQLAlchemy ORM models (SQLite via aiosqlite)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    contact_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    commodity = Column(String(100), nullable=True, default="rice")
    price_per_kg = Column(Float, nullable=True)
    contract_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    scans = relationship("Scan", back_populates="vendor")


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    original_path = Column(String(1024), nullable=False)
    annotated_path = Column(String(1024), nullable=True)

    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True, index=True)
    lot_id = Column(String(255), nullable=True)

    dpi = Column(Integer, nullable=False)
    width_px = Column(Integer, nullable=False)
    height_px = Column(Integer, nullable=False)
    width_mm = Column(Float, nullable=False)
    height_mm = Column(Float, nullable=False)

    grain_count = Column(Integer, nullable=True)
    processing_time_s = Column(Float, nullable=True)

    # "pending" | "processing" | "done" | "error"
    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)

    scanner_info = Column(JSON, nullable=True)
    processing_params = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    grains = relationship("Grain", back_populates="scan", cascade="all, delete-orphan")
    vendor = relationship("Vendor", back_populates="scans")


class Grain(Base):
    __tablename__ = "grains"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    grain_index = Column(Integer, nullable=False)

    # ── Pixel measurements ──────────────────────────────────────────────────
    area_px = Column(Float, nullable=False)
    perimeter_px = Column(Float, nullable=False)
    major_axis_px = Column(Float, nullable=False)
    minor_axis_px = Column(Float, nullable=False)
    centroid_x_px = Column(Float, nullable=False)
    centroid_y_px = Column(Float, nullable=False)

    # ── Millimetre measurements ──────────────────────────────────────────────
    area_mm2 = Column(Float, nullable=False)
    perimeter_mm = Column(Float, nullable=False)
    major_axis_mm = Column(Float, nullable=False)
    minor_axis_mm = Column(Float, nullable=False)
    centroid_x_mm = Column(Float, nullable=False)
    centroid_y_mm = Column(Float, nullable=False)

    # ── Derived ──────────────────────────────────────────────────────────────
    aspect_ratio = Column(Float, nullable=False)
    orientation_deg = Column(Float, nullable=False)
    solidity = Column(Float, nullable=True)
    eccentricity = Column(Float, nullable=True)

    # ── Bounding box ─────────────────────────────────────────────────────────
    bbox_x = Column(Integer, nullable=False)
    bbox_y = Column(Integer, nullable=False)
    bbox_w = Column(Integer, nullable=False)
    bbox_h = Column(Integer, nullable=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    scan = relationship("Scan", back_populates="grains")


class CalibrationProfileDB(Base):
    __tablename__ = "calibration_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    dpi = Column(Integer, nullable=False)
    px_per_mm = Column(Float, nullable=False)
    reference_type = Column(String(50), nullable=True)
    reference_size_mm = Column(Float, nullable=True)
    reference_size_px = Column(Float, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
