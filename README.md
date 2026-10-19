# Watch Me Bro — self-hosted video studio

A single-owner, local-first video editing and AI-assisted gaming-highlight
studio. It runs with Docker Compose on a Linux host; original videos, projects,
provider credentials and exports remain on storage you control. This project
is the self-hosted edition, not the separate Vercel/cloud edition.

## Features

- Upload and validate videos; preserve originals and record source hashes.
- Review timestamped gameplay highlights from sampled frames, then trim and
  crop selected sections in the visual timeline editor.
- Add editable captions, title cards, 3D-style titles, end screens, reviewed
  artwork and music, then export landscape or vertical video.
- Optionally connect supported AI providers or a trusted local LM Studio host.
  Paid calls require configuration, disclosure and confirmation; model-list
  discovery is not proof that inference works.
- Review output and approve it locally. This edition does not publish to social
  platforms.

This is single-owner self-hosted software, not a public multi-tenant service.
Do not expose it directly to the internet or accept uploads from untrusted users.
Use a private LAN/WireGuard/firewall path and a properly configured TLS proxy.

## Quick start

Requirements: Linux, Docker Engine with Compose, FFmpeg-compatible CPU resources,
and enough disk for source videos and exports. The default application account
inside the container is UID/GID 1000; adjust ownership for your host setup.

```sh
cp .env.example .env
mkdir -p private/data media backups media-backups
chmod 700 private private/data
umask 077
openssl rand -base64 36 > private/admin-password
head -c 32 /dev/urandom > private/credential-encryption-key
sudo chown -R 1000:1000 private media
sudo chmod 600 private/admin-password private/credential-encryption-key
```

Edit `.env` to use dedicated data/media/backup locations. Keep
`WMB_BIND_ADDRESS=127.0.0.1` unless you have configured and tested a firewall
and private TLS reverse proxy. Set `WMB_PORT` if 8787 is already occupied.

```sh
docker compose config --quiet
docker compose build studio
docker compose up -d studio
docker compose ps
```

Open `http://127.0.0.1:8787/` on the host. For remote use, connect through
WireGuard and a private TLS reverse proxy. Do not disable TLS validation or
publish the port directly. Read [deployment and security](docs/SECURITY.md)
before exposing the service to any network.

Provider credentials are configured only from the authenticated Settings page.
They are encrypted using `private/credential-encryption-key`; keep that file
private and include it in protected backups. Never commit `.env`, `private/`,
videos, database files or exports.

## Backups

Set the backup paths to match your deployment before running `backup.py`:

```sh
WMB_PRIVATE_DIR=./private \
WMB_MEDIA_ROOT=./media \
WMB_BACKUP_ROOT=./backups \
WMB_MEDIA_BACKUP_ROOT=./media-backups \
python3 backup.py
```

The backup script creates a consistent SQLite copy and verifies referenced media
checksums. Keep backups off the application disk as well; a backup on the same
host or physical drive does not protect against host or disk failure.

## Development

Install the pinned dependencies from `requirements.txt`. Run the unit tests with
`python3 -m unittest discover -s tests -p 'test_*.py'`. Integration and browser
checks require additional local tooling and are not run by this command. Review
[`SECURITY.md`](docs/SECURITY.md) before proposing public-network access.

## License

Licensed under the GNU Affero General Public License v3.0 or later; see
[`LICENSE`](LICENSE).
