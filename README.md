# TRIMIQ LIVE

TRIMIQ LIVE is a mobile-responsive Flask dashboard for managing MP4 uploads,
playlists, RTMP destinations, stream history and one FFmpeg streaming process.

## Important deployment modes

- `STREAMING_MODE=DEMO` (default): the dashboard and process-control UI are fully
  usable, but stream status is simulated and no public broadcast is started.
- `STREAMING_MODE=PRODUCTION`: requires FFmpeg and a suitable always-on Linux host.
  The application never falls back to DEMO in this mode.

Railway Free is suitable for dashboard development only. Continuous FFmpeg
streaming is not a suitable permanent use of the Railway Free tier.

## Run frontend and backend with one command

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
chmod +x start.sh
./start.sh
```

The Flask server serves the frontend and API together, so `./start.sh` starts
both in one command. It loads `.env` when present and initializes the database
automatically. Open `http://localhost:8080`. Change `ADMIN_PASSWORD` in `.env`
before starting. The default development credentials are
`admin` / `change-this-password`.

FFmpeg and FFprobe are optional for dashboard-only/DEMO use. For production,
install them and set `STREAMING_MODE=PRODUCTION`.

## Environment

See `.env.example`. Set a stable `SECRET_KEY` and `KEY_ENCRYPTION_KEY` on every
deployment. Store stream keys only in the encrypted SQLite field or future
PostgreSQL migration; they are never returned by list/detail APIs or written to
stream history.

## Docker

```bash
docker build -t trimiqlive .
docker run --rm -p 8080:8080 \
  -e STREAMING_MODE=DEMO \
  -e ADMIN_PASSWORD='replace-me' \
  -e SECRET_KEY='replace-me' \
  -e KEY_ENCRYPTION_KEY='replace-me' \
  -v trimiqlive-data:/app/data \
  -v trimiqlive-uploads:/app/uploads \
  trimiqlive
```

## Railway

1. Import this repository.
2. Set `STREAMING_MODE=DEMO`.
3. Set secure `SECRET_KEY`, `KEY_ENCRYPTION_KEY`, `ADMIN_USERNAME` and
   `ADMIN_PASSWORD` variables.
4. Add persistent volumes for `/app/data` and `/app/uploads` if available.
5. Deploy with the Dockerfile.

No real RTMP broadcast should be started on Railway Free.

## Future VPS

Start with at least 2 GB RAM, 1 vCPU, 30 GB SSD, stable network bandwidth and
FFmpeg/FFprobe installed. Use a persistent volume for `data/`, `uploads/`,
`playlists/` and `logs/`, enable TLS for public access, and set
`STREAMING_MODE=PRODUCTION`. The streaming process uses stream-copy by default
and rejects source resolutions that do not match the selected 9:16 or 16:9
target. Re-encoding/transcoding is deliberately not silently claimed or added.

Test destinations and obtain your own credentials from:

- YouTube: <https://support.google.com/youtube/answer/2907883>
- FFmpeg: <https://ffmpeg.org/ffmpeg.html>
- FFprobe: <https://ffmpeg.org/ffprobe.html>
- Railway: <https://docs.railway.com/pricing/free-plan>

Meta accounts and RTMP settings must be configured from Meta Live Producer
documentation.

## Tests

```bash
python3 -m pytest -q
```
