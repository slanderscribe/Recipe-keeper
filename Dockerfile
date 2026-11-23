FROM python:3.12-slim

# Tesseract reads text from recipe photos (see capture.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Same start command as the Procfile; Railway supplies $PORT.
CMD ["sh", "-c", "gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8080}"]
