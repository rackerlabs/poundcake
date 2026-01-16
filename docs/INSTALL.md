# Installation Guide

## Using pyproject.toml

PoundCake API uses pyproject.toml for dependency management and project configuration.

## Quick Install

### Production

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip and install build tools
pip install --upgrade pip setuptools wheel

# Install the application
pip install .
```

### Development

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip and install build tools
pip install --upgrade pip setuptools wheel

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

## Why the Upgrade Command?

The command `pip install --upgrade pip setuptools wheel` is important because:

1. **pip** - Package installer needs to be latest version
2. **setuptools** - Build backend specified in pyproject.toml
3. **wheel** - Build format for Python packages

Without these, you may see errors like:
- "Cannot import 'setuptools.build_backend'"
- "No module named 'setuptools'"
- Build failures

## What Gets Installed

### Production Dependencies
```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.25
alembic>=1.13.1
pymysql>=2.9.9
celery[redis]>=5.3.6
redis>=5.0.1
pydantic>=2.6.0
pydantic-settings>=2.1.0
python-json-logger>=2.0.7
```

### Development Dependencies (with [dev])
All production dependencies plus:
```
pytest>=7.4.4
pytest-asyncio>=0.23.3
pytest-cov>=4.1.0
httpx>=0.26.0
black>=24.1.1
ruff>=0.1.14
mypy>=1.8.0
```

## System Requirements

### Python Version
Requires Python 3.11 or higher

Check version:
```bash
python3 --version
```

### System Dependencies

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-dev default-libmysqlclient-dev gcc
```

#### CentOS/RHEL
```bash
sudo yum install -y python311 python311-devel mysql+pymysql-devel gcc
```

#### macOS
```bash
brew install python@3.11 mysql+pymysql
```

## Complete Setup Example

```bash
# 1. Install system dependencies (Ubuntu example)
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv default-libmysqlclient-dev gcc

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 3. Upgrade pip and install build tools
pip install --upgrade pip setuptools wheel

# 4. Install application with dev dependencies
pip install -e ".[dev]"

# 5. Verify installation
python -c "import fastapi, celery, sqlalchemy; print('Installation successful')"
```

## Docker Installation

Docker handles dependencies automatically via the Dockerfile:

```bash
# Build image
docker-compose build

# Start services
docker-compose up -d
```

No manual pip installation needed when using Docker.

## Troubleshooting

### Error: "Cannot import 'setuptools.build_backend'"

**Solution:** Upgrade pip and install setuptools
```bash
pip install --upgrade pip setuptools wheel
pip install .
```

### Error: "No module named 'setuptools'"

**Solution:** Install setuptools explicitly
```bash
pip install setuptools>=61.0
pip install .
```

### Error: pymysql compilation fails

**Solution:** Install MariaDB development libraries
```bash
# Ubuntu/Debian
sudo apt-get install default-libmysqlclient-dev python3-dev

# CentOS/RHEL
sudo yum install mysql+pymysql-devel python3-devel

# macOS
brew install mysql+pymysql
```

### Error: Permission denied

**Solution:** Always use virtual environment (never use sudo)
```bash
python3 -m venv venv
source venv/bin/activate
pip install .
```

## Verifying Installation

### Test Script

Save as `test_install.py`:

```python
#!/usr/bin/env python3
"""Verify PoundCake API installation."""

import sys

def test_imports():
    """Test all critical imports."""
    try:
        print("Testing imports...")
        
        import fastapi
        print(f"  fastapi: {fastapi.__version__}")
        
        import uvicorn
        print(f"  uvicorn: {uvicorn.__version__}")
        
        import sqlalchemy
        print(f"  sqlalchemy: {sqlalchemy.__version__}")
        
        import celery
        print(f"  celery: {celery.__version__}")
        
        import redis
        print(f"  redis: {redis.__version__}")
        
        import pydantic
        print(f"  pydantic: {pydantic.__version__}")
        
        print("\nAll imports successful!")
        return True
        
    except ImportError as e:
        print(f"\nError: {e}")
        return False

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
```

Run it:
```bash
python test_install.py
```

## Editable Install vs Regular Install

### Regular Install: `pip install .`
- Installs package into site-packages
- Changes to source code not reflected until reinstall
- Use for production

### Editable Install: `pip install -e .`
- Creates link to source code
- Changes to source code immediately reflected
- Use for development

## Updating Dependencies

### View Installed Packages
```bash
pip list
```

### Check for Updates
```bash
pip list --outdated
```

### Update All Packages
```bash
pip install --upgrade .
```

### Update Specific Package
Edit pyproject.toml, then:
```bash
pip install --upgrade .
```

## Uninstalling

```bash
pip uninstall poundcake-api
```

## Next Steps

After installation:

1. Configure environment variables in `.env`
2. Start services with `docker-compose up -d`
3. Test API: `curl http://localhost:8000/api/v1/health`
4. View docs: `http://localhost:8000/docs`

See README.md for complete documentation.
