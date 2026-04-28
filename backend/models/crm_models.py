from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="agent")  # admin, manager, agent, readonly
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    industry = Column(String)
    phone = Column(String)
    email = Column(String)
    address = Column(String)
    city = Column(String)
    country = Column(String, default="Tunisia")
    website = Column(String)
    status = Column(String, default="prospect")  # prospect, client, inactive
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    contacts = relationship("Contact", back_populates="company")
    deals = relationship("Deal", back_populates="company")
    activities = relationship("Activity", back_populates="company")


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, index=True)
    phone = Column(String)
    role = Column(String)  # CEO, Sales Manager, etc.
    is_primary = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="contacts")
    activities = relationship("Activity", back_populates="contact")


class Deal(Base):
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    title = Column(String, nullable=False)
    value = Column(Float, default=0.0)
    currency = Column(String, default="TND")
    status = Column(String, default="open")  # open, won, lost, on_hold
    stage = Column(String, default="prospecting")  # prospecting, qualification, proposal, negotiation, closed
    probability = Column(Integer, default=50)  # 0-100%
    expected_close_date = Column(DateTime)
    closed_at = Column(DateTime)
    notes = Column(Text)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="deals")


class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    type = Column(String)  # call, meeting, email, task, note
    title = Column(String, nullable=False)
    description = Column(Text)
    due_date = Column(DateTime)
    done = Column(Boolean, default=False)
    done_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="activities")
    contact = relationship("Contact", back_populates="activities")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)       # CREATE, UPDATE, DELETE, READ
    entity = Column(String, nullable=False)        # company, contact, deal, activity
    entity_id = Column(Integer, nullable=True)
    payload = Column(JSON)
    result = Column(String)                        # success, error
    timestamp = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)          # UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    messages = Column(JSON, default=list)           # list of {role, content}
    pending_action = Column(JSON, nullable=True, default=None)  # {"tool": str, "params": dict}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
