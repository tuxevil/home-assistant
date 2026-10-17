FROM alpine:3.23
RUN apk add --no-cache ffmpeg python3 py3-aiohttp py3-zmq font-dejavu tzdata mesa-va-gallium libva-utils
RUN if [ "$(apk --print-arch)" = "x86_64" ]; then apk add --no-cache intel-media-driver libva-intel-driver; fi
RUN mkdir -p /data /media/live_studio
WORKDIR /app
COPY studio /app/studio
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "studio.server"]
