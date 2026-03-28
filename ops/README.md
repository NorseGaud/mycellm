# mycellm Operations

Infrastructure configuration tracked in this directory. The canonical configs
live on the servers; these files are reference copies for version control.

## Structure

```
ops/
  caddy/
    mycellm.caddyfile   # All mycellm Caddy blocks (docker-box /etc/caddy/Caddyfile)
  backup/
    README.md           # Backup coverage and restore notes
```

## Servers

| Server | IP | Role |
|--------|-----|------|
| docker-box | 96.126.98.204 | Bootstrap node + static sites |

## Key Paths (docker-box)

- Caddyfile: `/etc/caddy/Caddyfile`
- Backup script: `/opt/backup/bin/backup.sh`
- Backup config: `/opt/backup/etc/backup.conf`
- Static sites: `/srv/www/mycellm.ai`, `/srv/www/mycellm-dev`, `/srv/www/docs-mycellm-dev`
- Docker compose: `/srv/docker/mycellm/app/docker/`
- Data volume: `mycellm_mycellm-data` (keys, certs, node identity)
