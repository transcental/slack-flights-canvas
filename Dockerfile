# Use Python 3.13 as base image
FROM python:3.13-slim

# Install Node. js 20 and curl
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install. sh | sh

# Set working directory
WORKDIR /app

# Copy package files first
COPY package.json package-lock.json ./

# Copy pyproject. toml
COPY pyproject.toml ./

# Add uv to PATH and install Python dependencies
ENV PATH="/root/.cargo/bin:$PATH"
RUN /root/.cargo/bin/uv sync

# Install Node.js dependencies
RUN npm ci

# Copy application code
COPY .  .

# Build frontend assets
RUN npm run build

# Expose port (default 5000, can be overridden with PORT env var)
EXPOSE 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["uv", "run", "main.py"]
