# =============================================================================
# Dockerfile — pv-report-automation
# =============================================================================
# Multi-stage build for a lightweight production container.
#
# Design decisions:
#   - python:3.9-slim: Minimal footprint (~120MB vs ~900MB full image).
#   - Non-root user: Security best practice for production containers.
#   - HEALTHCHECK: Enables orchestrators (Docker Swarm, K8s) to monitor
#     container health and restart if the process hangs.
#   - .dockerignore: Prevents unnecessary files from bloating the image.
#
# Usage:
#   docker build -t pv-report-automation .
#   docker run --rm -v $(pwd)/output:/app/output pv-report-automation
#
# Author: Miguel Ángel Mejía Sánchez
# =============================================================================

FROM python:3.9-slim AS base

# Metadata labels (OCI standard)
LABEL maintainer="Miguel Ángel Mejía Sánchez"
LABEL description="Solar Plant Maintenance Intelligence Suite"
LABEL version="2.0.0"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Install dependencies first (leverages Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/
COPY main.py .
COPY sample_data/ ./sample_data/

# Create output directory with correct permissions
RUN mkdir -p /app/output && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check: verify Python and dependencies are functional
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import pandas; import plotly; print('healthy')" || exit 1

# Default command
ENTRYPOINT ["python", "main.py"]
CMD ["--input", "sample_data/plant_log_2024.csv", "--output", "output"]
