FROM python:3.12-slim

# China mirror for apt (comment out if not in China)
RUN sed -i 's@//deb.debian.org@//mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# Install adb (android-tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY start.sh ./
RUN chmod +x start.sh

# Install project and dependencies
RUN uv pip install --system --no-cache .

# Create directories
RUN mkdir -p logs screenshots config

ENTRYPOINT ["./start.sh"]
