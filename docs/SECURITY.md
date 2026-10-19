# Security and network exposure

This edition is a private, single-owner application. It is not designed or
approved for public multi-user access. Application login is not a substitute
for network isolation. Do not bind its port to a public interface, configure a
public DNS/reverse-proxy route, or accept untrusted uploads.

## Minimum deployment controls

- Use a dedicated host or VM, updated Docker Engine, WireGuard/private LAN and
  firewall rules that permit only trusted devices. Keep the default host bind
  address on loopback and use a correctly configured TLS reverse proxy for
  remote access.
- Do not add a Docker socket, host networking, privileged mode, devices or
  additional Linux capabilities. The provided container runs as a non-root UID,
  with a read-only root filesystem and bounded CPU, memory, PIDs and temporary
  storage.
- Keep `.env`, `private/`, provider keys, the admin password, encryption key,
  videos, database and exports out of Git and public backups. Restrict secret
  files to the container's configured owner. Use off-host encrypted backups.
- Configure provider-side billing limits. Local estimates and caps are not
  guaranteed billing ceilings. Review every disclosure before sending text or
  sampled images to a provider.
- Treat uploaded video and image files as untrusted parser input. FFprobe, FFmpeg
  and image decoders run inside the application container; this release does
  **not** provide per-job VM isolation. Do not use it as a public upload service.
  A future cloud release needs isolated per-job media processing, tenant quotas
  and security/integration testing before public exposure.
- Keep Docker, FFmpeg, Python dependencies and the host OS patched. Review
  dependency advisories and backups regularly.

## Secrets and data

The admin password and AES key are mounted read-only from host files. The AES
key must be backed up separately from the database; without it saved provider
credentials cannot be decrypted. A host or running-container compromise can
access the mounted credentials and application media. Logs and task notes must
not contain credentials or footage.

## Reporting a vulnerability

Please do not file exploitable details in a public issue. Contact the repository
maintainer privately and include affected version, impact and a reproducible
description. Allow time to investigate and prepare a fix before public
disclosure.
