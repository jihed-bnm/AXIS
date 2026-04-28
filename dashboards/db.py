from sqlalchemy import create_engine, text
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()


def get_engine():
    return create_engine(os.getenv("DATABASE_URL"))


def query(sql, params=None):
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)
