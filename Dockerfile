# Pinned to Debian 12 (bookworm). Debian 13 (trixie) renamed libasound2 -> libasound2t64
# and dropped libgconf-2-4, which breaks the Cypress 15.x binary at runtime
# (libgtk-3.so.0: cannot open shared object file). Do NOT bump to slim-trixie
# without also reworking the apt list below.
FROM python:3.11-slim-bookworm

WORKDIR /app

# System deps for Node, Cypress, and Playwright/Chromium.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends \
        nodejs npm curl gnupg \
        # Cypress runtime
        libgtk-3-0 libgtk2.0-0 libnotify-dev libgconf-2-4 \
        libnss3 libxss1 libasound2 libxtst6 xauth xvfb \
        # Playwright / Chromium runtime
        libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
        libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Install Node.js dependencies (Cypress + eslint)
COPY package.json . package-lock.json* ./
RUN npm install

# Copy application source
COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
