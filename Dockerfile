# Base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies including Node.js and build tools for psutil
RUN apt-get update && apt-get install -y --no-install-recommends \
    tar \
    gzip \
    curl \
    nodejs \
    npm \
    gcc \
    g++ \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy tool_log_decompress to system directory (as root)
COPY bin/tool_log_decompress /usr/local/bin/
RUN chmod +x /usr/local/bin/tool_log_decompress

# Create a non-root user
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies (as root first)
COPY requirements.txt .

# Upgrade pip and configure for better network handling
RUN pip install --upgrade pip

# Install dependencies with increased timeout and retries
RUN pip install --no-cache-dir \
    --timeout 300 \
    --retries 5 \
    --trusted-host pypi.org \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org \
    -r requirements.txt

# Copy application code and change ownership
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p /app/logs /app/temp/logs /app/temp/downloads /app/data

# Make cleanup script executable
RUN chmod +x /app/cleanup_runtime_data.py

RUN chown -R appuser:appuser /app

# Build frontend (as root before changing ownership)
WORKDIR /app/frontend
RUN if [ -f package.json ]; then \
    npm install && \
    npm run build; \
    fi

# Change ownership and switch back to app directory
WORKDIR /app
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD [ "curl", "-f", "http://localhost:8085/health" ]

# Expose port and run the application
EXPOSE 8085
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085"]