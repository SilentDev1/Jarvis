# Jarvis AiPi firmware

Version `0.1.0-bringup` is the first controlled hardware-validation image. It
initializes serial logging and octal PSRAM, renders a simple ST7735 status
screen, debounces the active-low GPIO42 side button, and probes the ES8311 on
GPIO4/GPIO5. The speaker amplifier is forced off and GPIO10 board power is never
configured. Audio, Wi-Fi, and the local WebSocket remain later validation stages.

Do not run `idf.py erase-flash` against the factory device. Build with
`scripts/aipi-build.sh`. The flash wrapper refuses to run unless the separately
verified recovery gate marker exists and explicit flash authorization is set.
