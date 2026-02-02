#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 1. Create user FIRST so we can use it for COPY
RUN useradd -m -u 1000 appuser

# 2. Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy EVERYTHING and set ownership to appuser immediately
# This avoids most "Permission Denied" errors at runtime
COPY --chown=appuser:appuser . .

# 4. Final permission fix as root before switching
RUN chmod +x /app/api/scripts/entrypoint.sh

# Switch to the restricted user
USER appuser

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command (Uvicorn fallback)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
