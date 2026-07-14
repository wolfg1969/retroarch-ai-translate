FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    LISTEN_HOST=0.0.0.0 \
    LISTEN_PORT=4404 \
    GAME_CONFIG_PATH=/app/game_config.yaml \
    GAME_CONFIG_DIR=/config/games \
    PADDLE_HOME=/models/paddle \
    XDG_CACHE_HOME=/models/cache

WORKDIR /app

RUN set -eux; \
    sed -i \
      -e 's|http://deb.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' \
      -e 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' \
      /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        fonts-wqy-zenhei \
        tesseract-ocr \
        tesseract-ocr-jpn; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /config/games /models

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY src/retroarch_translate.py /app/src/retroarch_translate.py
COPY templates/game_config.yaml /app/game_config.yaml

EXPOSE 4404

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:4404/', timeout=3).read()"

CMD ["python", "/app/src/retroarch_translate.py"]
