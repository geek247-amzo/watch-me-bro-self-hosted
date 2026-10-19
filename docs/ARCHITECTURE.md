# Architecture

The Python HTTP application serves a static browser UI and authenticated API.
SQLite stores one owner's projects, source metadata, edits, queue, reviews,
provider usage and audit records. Original sources and generated exports are
stored under the mounted media directory. FFprobe/FFmpeg render jobs run in a
single sequential background worker. Render progress is derived from FFmpeg
reports and recent measured stage timing; unknown durations remain unknown.

The container intentionally has no public bind by default beyond the loopback
host port in Compose. It runs as UID 1000 with read-only root, dropped
capabilities, no-new-privileges and explicit CPU/RAM/PID/tmpfs bounds. Host
mounted data, media and secret paths are configured by the operator.

This architecture is local-first and single-owner. The renderer shares one
application container and persistent mounts; it is not an isolated sandbox for
hostile uploads. It is not suitable for public multi-tenant hosting. The Vercel
web edition requires a distinct cloud architecture for durable storage, queueing,
tenant isolation and per-job media sandboxing.
