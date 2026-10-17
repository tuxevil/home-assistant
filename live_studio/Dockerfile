FROM alpine:3.23
RUN apk add --no-cache ffmpeg python3 py3-aiohttp font-dejavu tzdata
RUN mkdir -p /data /media/live_studio
WORKDIR /app
COPY studio /app/studio
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "studio.server"]
