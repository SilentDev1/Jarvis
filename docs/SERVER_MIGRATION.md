# Mac to server migration

1. Stop writes on Mac and run `scripts/backup.sh`.
2. Deploy the same release on Linux.
3. Restore `data/` (database and media) and non-secret configuration.
4. Recreate secrets in server `.env`; update camera/AI/service hostnames only.
5. Start, verify every `/health/*` endpoint, simulator, RTSP, detection, and snapshots.
6. Run both only during a controlled read-only verification window; avoid two writers.
7. Switch production access and retire Mac service.

No application source or hard-coded user path changes are required. SQLite is suitable for one core instance; adopt PostgreSQL before active-active deployment.

