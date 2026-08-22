# Linux deployment

Docker Compose is preferred. Copy the repository and non-secret persistent backup, create a fresh `.env`, set host/device endpoints, then run `docker compose up -d`. Use a native vision sidecar behind the same provider interface if the server accelerator cannot be exposed to the main container.

