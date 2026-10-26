# Multi-stage build (same layout as sunlease-hrms1)
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl tesseract-ocr libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist
COPY startup.sh ./startup.sh
RUN chmod +x ./startup.sh && mkdir -p /data
ENV DEPOT_DATABASE_URL=sqlite:////data/depot.db
ENV DEPOT_RUNNING_IN_DOCKER=1
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1
CMD ["./startup.sh"]
