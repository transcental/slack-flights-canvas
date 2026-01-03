# Use Python 3.13 as base image
FROM python:3.13-slim

# 1. Install uv (Best Practice: Copy from official image)
# This places 'uv' directly in /bin, so it is automatically in the PATH.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. Install Node.js 20 and curl
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# 3. Copy python dependency files
# Note: It is highly recommended to include uv.lock if you have one
COPY pyproject.toml uv.lock* ./

# 4. Install Python dependencies
# --no-dev: prevents installing testing/dev dependencies in production
RUN uv sync --no-dev --no-cache

# 5. Copy Node dependency files and install
COPY package.json package-lock.json ./
RUN npm ci

# 6. Copy the rest of the application code
COPY . .

# 7. Build frontend assets
RUN npm run build

# Expose port
EXPOSE 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1
# Ensure the virtual environment created by uv is in the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
# Since we added .venv to PATH, we can run python directly, 
# but 'uv run' is also fine.
CMD ["uv", "run", "main.py"]
