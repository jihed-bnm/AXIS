from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://erp_user:erp_pass@localhost:5432/erp_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_session():
    """Plain session factory for non-FastAPI code (tools, scripts, agents).
    Caller is responsible for try/finally db.close()."""
    return SessionLocal()


def get_db():
    """FastAPI dependency — yields a DB session via Depends()."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create tables for active modules (CRM and Invoicing only)."""
    # Import only the active models so Base.metadata only includes their tables.
    import backend.models.crm_models      # noqa: F401
    import backend.models.invoice_models  # noqa: F401
    import backend.models.warehouse_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
