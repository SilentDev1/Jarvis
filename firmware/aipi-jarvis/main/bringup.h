#pragma once

#include <stdbool.h>
#include "esp_err.h"

esp_err_t bringup_display_init(void);
void bringup_display_status(const char *line1, const char *line2, const char *line3);
void bringup_display_status4(const char *line1, const char *line2, const char *line3,
                             const char *line4);
esp_err_t bringup_button_start(void);
bool bringup_codec_probe(void);
