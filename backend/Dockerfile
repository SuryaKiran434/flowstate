FROM python:3.11-slim

WORKDIR /app

# System dependencies:
#   gcc, libpq-dev  — psycopg2
#   libsndfile1     — librosa audio I/O
#   ffmpeg          — audio decoding for librosa + required by yt-dlp for audio extraction
#   curl            — yt-dlp download
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (includes yt-dlp)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
