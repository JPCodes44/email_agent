FROM oven/bun:1 AS base
WORKDIR /app

COPY package.json bun.lock* ./
COPY frontend/package.json frontend/
COPY backend/package.json backend/
COPY common/package.json common/

RUN bun install

COPY common/ common/
COPY backend/ backend/

WORKDIR /app/backend
CMD ["bun", "run", "start"]
