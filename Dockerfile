FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY mtde ./mtde
RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /usr/local/bin/mtde-entrypoint
RUN chmod +x /usr/local/bin/mtde-entrypoint

ENV PYTHONUNBUFFERED=1 \
    MTDE_CONFIG=/config/config.yml \
    PUID=99 \
    PGID=100

VOLUME ["/config", "/media", "/cookies"]
EXPOSE 2121
ENTRYPOINT ["/usr/local/bin/mtde-entrypoint"]
CMD []
