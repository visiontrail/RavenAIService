# Base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tar \
    gzip \
    curl \
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
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and change ownership
COPY . .
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD [ "curl", "-f", "http://localhost:8085/health" ]

# Expose port and run the application
EXPOSE 8085
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085"]