#pragma once

#include <stdbool.h>
#include "esp_err.h"

typedef struct {
    bool configured;
    bool connected;
    char ip[16];
    int retry_count;
} wifi_provision_status_t;

esp_err_t wifi_provision_start(void);
wifi_provision_status_t wifi_provision_status(void);
bool wifi_provision_boot_reset_requested(void);
esp_err_t wifi_provision_clear_custom_config(void);
