FROM apache/airflow:2.8.0-python3.11

# Switch to root to install system dependencies
USER root

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Switch back to airflow user for pip installs
USER airflow

# Pre-bake all ML/audio dependencies so they survive container restarts.
# These are NOT in the base airflow image and were previously lost on every
# docker-compose down/up cycle.
RUN pip install --no-cache-dir --user \
    "numpy>=1.26.4" \
    librosa==0.10.1 \
    yt-dlp>=2024.1.0 \
    httpx==0.25.2 \
    scipy==1.11.4 \
    scikit-learn==1.3.2
