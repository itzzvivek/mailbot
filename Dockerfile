FROM python:3.14.5-slim

WORKDIR /app

copy requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app
USER appuser


VOLUME ["/app/data"]

CMD ["python", "main.py"]