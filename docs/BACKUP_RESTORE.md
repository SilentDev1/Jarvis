# Backup and restore

`scripts/backup.sh` archives `data/` and optional non-secret `config/` to `backups/`; `.env` is excluded. Stop Jarvis for a fully consistent SQLite filesystem backup. Restore by extracting into a stopped deployment, verify ownership, then run tests and `/health/database`. Store secrets separately in a password manager.

