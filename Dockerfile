FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY requirements-demo.lock ./
RUN pip install --no-cache-dir -r requirements-demo.lock
COPY . .
RUN useradd -m -u 10001 strive && mkdir -p /app/data && chown -R strive:strive /app
USER strive
ENV STRIVE_MODE=demo HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1
EXPOSE 8000
CMD ["python", "scripts/start.py", "--host", "0.0.0.0"]
