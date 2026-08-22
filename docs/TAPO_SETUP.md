# Tapo C101 setup

Create a camera account in the Tapo app (not the cloud account password), enable local RTSP, reserve the camera IP, and put host/user/password in `.env`. Common URLs are `rtsp://user:password@host:554/stream1` (main) and `/stream2` (sub). Explicit URL variables override construction. Validate with `doctor.sh`. Never commit or paste the populated URL into logs/issues.

