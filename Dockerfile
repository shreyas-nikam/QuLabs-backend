FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt /app
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Expose the FastAPI default port (if you run on 8002)
EXPOSE 8002

# Run via gunicorn + uvicorn workers (common production pattern)
CMD ["gunicorn", "main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8002"]
