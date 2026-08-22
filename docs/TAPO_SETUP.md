# Tapo C101 setup

Create a camera account in the Tapo app (not the cloud account password), enable local RTSP, reserve the camera IP, and put host/user/password in `.env`. Common URLs are `rtsp://user:password@host:554/stream1` (main) and `/stream2` (sub). Explicit URL variables override construction. Validate with `doctor.sh`. Never commit or paste the populated URL into logs/issues.

Recommended setup:

```sh
./scripts/configure-tapo.sh
./scripts/test-camera.sh
```

The connectivity test checks TCP/554, authentication, codec/resolution/FPS for both streams, main-stream snapshot decode, and a clean reconnect. It passes URLs only as subprocess arguments and never prints them. Use explicit `CAMERA_RTSP_URL_MAIN` and `CAMERA_RTSP_URL_SUB` instead of host credentials only when the camera uses nonstandard paths.
