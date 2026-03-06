FROM python:3.12-slim

# China mirror for apt
RUN sed -i 's@//deb.debian.org@//mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# Install adb
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (use GitHub mirror for China)
RUN curl -LsSf https://ghfast.top/https://github.com/astral-sh/uv/releases/latest/download/uv-installer.sh | sh \
    || curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY start.sh ./
RUN chmod +x start.sh

# Install project and dependencies (use Tsinghua PyPI mirror)
RUN uv pip install --system --no-cache --index-url https://pypi.tuna.tsinghua.edu.cn/simple .

# Create directories
RUN mkdir -p logs screenshots config

ENTRYPOINT ["./start.sh"]
