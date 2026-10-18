# Keep the bundled engine on the same FFmpeg major version as the reference
# Linux deployment: some FFmpeg8 builds crash on live drawtext resizing.
FROM debian:trixie-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg python3 python3-aiohttp python3-zmq python3-numpy python3-pil fonts-dejavu-core tzdata mesa-va-drivers vainfo \
    && if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        apt-get install -y --no-install-recommends intel-media-va-driver i965-va-driver; \
       fi \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /data /media/live_studio
WORKDIR /app
COPY studio /app/studio
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "studio.server"]
