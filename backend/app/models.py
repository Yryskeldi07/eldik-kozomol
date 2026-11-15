import enum, uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, String, Text, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Status(str, enum.Enum):
    new='new'; review='review'; referred='referred'; need_info='need_info'; closed='closed'

class Report(Base):
    __tablename__='reports'
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    public_code: Mapped[str]=mapped_column(String(20), unique=True, index=True)
    language: Mapped[str]=mapped_column(String(2), default='ru')
    category: Mapped[str]=mapped_column(String(40), index=True)
    region: Mapped[str|None]=mapped_column(String(100), nullable=True)
    district: Mapped[str|None]=mapped_column(String(100), nullable=True)
    description: Mapped[str]=mapped_column(Text)
    status: Mapped[Status]=mapped_column(Enum(Status), default=Status.new, index=True)
    assigned_staff_id: Mapped[str|None]=mapped_column(String(36), ForeignKey('staff.id'), nullable=True)
    priority: Mapped[str]=mapped_column(String(20), default='normal', index=True)
    due_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc), onupdate=lambda:datetime.now(timezone.utc))

class Staff(Base):
    __tablename__='staff'
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    full_name: Mapped[str]=mapped_column(String(160), nullable=False)
    position: Mapped[str]=mapped_column(String(120), nullable=False)
    department: Mapped[str|None]=mapped_column(String(160), nullable=True)
    active: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))

class AdminUser(Base):
    __tablename__='admin_users'
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    username: Mapped[str]=mapped_column(String(80), unique=True, index=True)
    email: Mapped[str]=mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str]=mapped_column(String(160), default='')
    password_hash: Mapped[str]=mapped_column(String(300))
    role: Mapped[str]=mapped_column(String(30), default='operator', index=True)
    active: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
    last_login_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)

class AuditEvent(Base):
    __tablename__='audit_events'
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    report_id: Mapped[str]=mapped_column(String(36), ForeignKey('reports.id', ondelete='CASCADE'), index=True)
    actor: Mapped[str]=mapped_column(String(160), default='Администратор')
    action: Mapped[str]=mapped_column(String(80))
    details: Mapped[str]=mapped_column(Text, default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))

class InternalNote(Base):
    __tablename__='internal_notes'
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    report_id: Mapped[str]=mapped_column(String(36), ForeignKey('reports.id', ondelete='CASCADE'), index=True)
    author: Mapped[str]=mapped_column(String(160), default='Администратор')
    body: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))

class Attachment(Base):
    __tablename__='attachments'
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    report_id: Mapped[str]=mapped_column(String(36), ForeignKey('reports.id', ondelete='CASCADE'), index=True)
    original_name: Mapped[str]=mapped_column(String(255))
    stored_name: Mapped[str]=mapped_column(String(255), unique=True)
    content_type: Mapped[str]=mapped_column(String(120), default='application/octet-stream')
    size: Mapped[int]=mapped_column(Integer)
    uploaded_by: Mapped[str]=mapped_column(String(160))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
