"""Initialize database with new Recipe/Oven/Alert schema."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.core.database import Base, engine
from api.models.models import Recipe, Oven, Alert
from api.core.logging import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


def init_database():
    """Initialize database tables."""
    try:
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created successfully")
        
        # Print table info
        tables = Base.metadata.tables.keys()
        logger.info(f"Created tables: {', '.join(tables)}")
        
    except Exception as e:
        logger.error(f"✗ Failed to create database tables: {e}", exc_info=True)
        sys.exit(1)


def seed_default_recipes():
    """Seed database with default recipes."""
    from sqlalchemy.orm import Session
    from api.core.database import SessionLocal
    
    db: Session = SessionLocal()
    
    try:
        # Check if recipes already exist
        existing_count = db.query(Recipe).count()
        if existing_count > 0:
            logger.info(f"Database already has {existing_count} recipes, skipping seed")
            return
        
        logger.info("Seeding default recipes...")
        
        # Default recipes
        default_recipes = [
            {
                "name": "default",
                "description": "Default recipe for unmatched alerts",
                "st2_workflow_ref": "remediation.default_workflow",
                "task_list": None,
            },
            {
                "name": "HostDown",
                "description": "Recipe for host down alerts",
                "st2_workflow_ref": "remediation.host_down_workflow",
                "task_list": None,
            },
            {
                "name": "HighMemory",
                "description": "Recipe for high memory alerts",
                "st2_workflow_ref": "remediation.memory_check_workflow",
                "task_list": None,
            },
            {
                "name": "DiskFull",
                "description": "Recipe for disk full alerts",
                "st2_workflow_ref": "remediation.disk_cleanup_workflow",
                "task_list": None,
            },
        ]
        
        for recipe_data in default_recipes:
            recipe = Recipe(**recipe_data)
            db.add(recipe)
        
        db.commit()
        logger.info(f"✓ Seeded {len(default_recipes)} default recipes")
        
    except Exception as e:
        logger.error(f"✗ Failed to seed recipes: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("PoundCake v2.0 Database Initialization")
    logger.info("=" * 60)
    
    # Initialize tables
    init_database()
    
    # Seed default recipes
    seed_default_recipes()
    
    logger.info("=" * 60)
    logger.info("Database initialization complete!")
    logger.info("=" * 60)
