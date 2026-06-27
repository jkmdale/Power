FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Unbuffered logs so `docker compose logs` is live.
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
