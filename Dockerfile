FROM python:3.15-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

# De Chromium van Debian speelt H.264 af (Twitch streamt daarin) en bestaat
# ook voor arm64, dus deze image werkt ook op een Raspberry Pi. Xvfb is het
# virtuele scherm: een gewone browser lijkt het meest op echt kijken.
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium xvfb fonts-liberation tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY drops_makker ./drops_makker
RUN pip install .

RUN useradd -m -u 1000 makker \
 && mkdir -p /data /tmp/.X11-unix \
 && chmod 1777 /tmp/.X11-unix \
 && chown makker /data
USER makker

# status.json wordt minstens elke tien minuten bijgewerkt.
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m \
  CMD python -c "import os,sys,time; sys.exit(time.time() - os.path.getmtime('/data/status.json') > 900)"

CMD ["drops-makker"]
