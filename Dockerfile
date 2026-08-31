FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    TZ=Asia/Jerusalem

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# gunicorn מריץ את application factory של Flask
CMD exec gunicorn "main:create_app()" \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 8 \
    --timeout 120
