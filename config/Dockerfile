FROM python:3.14-slim

# Create a non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install dependencies
COPY config/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src ./src

# Set python path and defaults
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV CODEX_PROXY_LOG_LEVEL=INFO

# Expose port
EXPOSE 8765

# Pre-create config directories for volume mounts
RUN mkdir -p /home/appuser/.config/codex-proxy /home/appuser/.codex &&     chown -R appuser:appuser /home/appuser/.config /home/appuser/.codex

# Switch to non-root user
USER appuser

# Run the application
CMD ["python", "-m", "codex_proxy"]
