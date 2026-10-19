FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'cryptography==50.0.2'
RUN pip install --no-cache-dir 'Pillow==13.0.0'
WORKDIR /app
COPY app.py /app/app.py
COPY highlights.py /app/highlights.py
COPY creative.py /app/creative.py
COPY framing.py /app/framing.py
COPY captions.py /app/captions.py
COPY titles.py /app/titles.py
COPY render_progress.py /app/render_progress.py
COPY local_ai.py /app/local_ai.py
COPY static /app/static
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["python", "app.py"]
