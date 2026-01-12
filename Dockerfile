FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system dependencies needed for some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

ENV PORT=8080
EXPOSE 8080

# Use shell form so $PORT is expanded by the shell at runtime
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
