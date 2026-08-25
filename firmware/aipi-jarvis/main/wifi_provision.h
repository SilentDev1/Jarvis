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
