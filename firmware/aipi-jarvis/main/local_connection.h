#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t local_connection_start(void);

/* Reports a physical button press to Jarvis. Returns false when there is no
 * authenticated session, so the caller can fall back to local behaviour. */
bool local_connection_button_pressed(void);

/* The single source of truth for the firmware version string, so log banners
 * cannot drift from what the device reports to Jarvis. */
const char *local_connection_firmware_version(void);
