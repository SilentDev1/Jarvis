#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

typedef struct {
    bool configured;
    bool connected;
    char ip[16];
    int retry_count;
} wifi_provision_status_t;

typedef struct {
    char host[81];
    uint16_t port;
    char device_password[65];
} jarvis_local_config_t;

esp_err_t wifi_provision_start(void);
wifi_provision_status_t wifi_provision_status(void);
bool wifi_provision_boot_reset_requested(void);
esp_err_t wifi_provision_clear_custom_config(void);
bool wifi_provision_load_jarvis_config(jarvis_local_config_t *config);

/* Last gateway address the device successfully reached.
 *
 * mDNS resolution of the configured .local name is not reliable on this
 * hardware and fails intermittently at boot, leaving the terminal on Wi-Fi but
 * unable to find Jarvis. Caching the address that last worked lets the device
 * recover without multicast. */
bool wifi_provision_cached_gateway_ip(char *out, size_t size);
void wifi_provision_store_gateway_ip(const char *ip);
