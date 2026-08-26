#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "cJSON.h"
#include "esp_err.h"

/* Owner-approved local OTA.
 *
 * An update is only ever started by an explicit offer from an authenticated
 * Jarvis gateway. The device verifies an RSA signature over the manifest and
 * the SHA-256 of the downloaded image before it will boot the new slot, so a
 * compromised gateway cannot install arbitrary firmware. */

typedef void (*ota_progress_fn)(const char *state, int percent, const char *detail);

/* Handles an OTA_OFFER control message. Returns immediately; the transfer runs
 * on its own task so the websocket connection is never blocked. */
esp_err_t ota_update_handle_offer(const cJSON *root, ota_progress_fn report);

/* True while a transfer is in flight, so playback and capture stay refused. */
bool ota_update_active(void);

/* Confirms the running image after its post-boot health window. Until this is
 * called the bootloader will roll back on the next reset. Safe to call when
 * the running image is already marked valid. */
esp_err_t ota_update_mark_valid(void);

/* True when the running image is booting for the first time and still has to
 * prove itself. */
bool ota_update_pending_verify(void);

/* Human-readable description of the running slot, for status reporting. */
const char *ota_update_running_slot(void);
