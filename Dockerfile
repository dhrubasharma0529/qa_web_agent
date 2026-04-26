FROM python:3.11-slim

WORKDIR /app

# Install Node.js + npm (needed for Cypress and eslint)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs npm curl gnupg \
        # Playwright system dependencies
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
        libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Install Node.js dependencies (Cypress + eslint)
COPY package.json .
RUN npm install

# Copy application source
COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
