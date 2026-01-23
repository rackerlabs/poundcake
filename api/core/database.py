"""Database configuration and session management."""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from api.core.config import settings

# Create engine
engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database using Alembic migrations.
    
    This function runs Alembic migrations to ensure the database schema
    is up to date. It's safe to call multiple times.
    """
    from alembic.config import Config
    from alembic import command
    import os
    
    # Get the directory containing this file
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini_path = os.path.join(current_dir, "alembic.ini")
    
    # Create Alembic config
    alembic_cfg = Config(alembic_ini_path)
    
    # Override database URL from settings
    alembic_cfg.set_main_option('sqlalchemy.url', settings.database_url)
    
    # Run migrations to head (latest version)
    command.upgrade(alembic_cfg, "head")
