from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Date
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, unique=True, nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    status = Column(String, default="draft")  # draft, sent, paid, overdue, cancelled
    subtotal = Column(Float, default=0.0)
    tax_rate = Column(Float, default=19.0)   # TVA TUNISIA = 19%
    tax_amount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    currency = Column(String, default="TND")
    issue_date = Column(Date)
    due_date = Column(Date)
    paid_at = Column(DateTime)
    notes = Column(Text)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("InvoiceItem", back_populates="invoice")
    payments = relationship("Payment", back_populates="invoice")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    description = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    unit_price = Column(Float, nullable=False)
    total = Column(Float, nullable=False)

    invoice = relationship("Invoice", back_populates="items")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String)  # bank_transfer, check, cash
    reference = Column(String)
    paid_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="payments")
