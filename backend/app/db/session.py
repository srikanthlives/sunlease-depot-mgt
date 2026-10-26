from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
