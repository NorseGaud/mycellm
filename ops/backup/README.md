# mycellm Backup Coverage

Backups run daily at 04:00 UTC via `/opt/backup/bin/backup.sh` on docker-box.
Remote destination: SFTP to `akira.zetaix.com:9911` (2 daily retained).

## What's Backed Up

| Asset | Method | Remote Label |
|-------|--------|-------------|
| Postgres DB (`mycellm`) | `pg_dump` + zstd | `docker` (via compose project match) |
| Docker compose files | tar + zstd | `docker` |
| Static site `/srv/www/mycellm.ai` | tar + zstd | `mycellm.ai` |
| Static placeholder `/srv/www/mycellm-dev` | tar + zstd | `mycellm-dev` |
| Static placeholder `/srv/www/docs-mycellm-dev` | tar + zstd | `docs-mycellm-dev` |
| Identity volume (`mycellm_mycellm-data`) | docker volume tar + zstd | `mycellm-identity` |
| Caddyfile | tar + zstd | `_global` |

## Identity Volume Contents

The `mycellm_mycellm-data` volume stores critical, non-regenerable data:

- `keys/` — Ed25519 account + device keypairs
- `certs/` — Identity certificates
- `tls/` — TLS certificates for QUIC transport
- `config/` — Bootstrap peer list, network config
- `federation/` — Federation state
- `node_state.json` — Node identity and state

**Losing this volume means losing the bootstrap node's identity on the network.**

## Restore

### Database
```bash
zstd -d < backup.sql.zst | docker exec -i mycellm-postgres-1 psql -U mycellm -d mycellm
```

### Identity Volume
```bash
docker volume create mycellm_mycellm-data
zstd -d < backup_vol.tar.zst | docker run --rm -i -v mycellm_mycellm-data:/vol alpine tar xf - -C /vol
```
