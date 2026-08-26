#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

esp_err_t es8311_codec_bus_initialize(void);
bool es8311_codec_probe(void);
esp_err_t es8311_codec_initialize_output(void);
esp_err_t es8311_codec_write_register(uint8_t reg, uint8_t value);
esp_err_t es8311_codec_read_register(uint8_t reg, uint8_t *value);
esp_err_t es8311_codec_set_volume(unsigned volume);
esp_err_t es8311_codec_set_muted(bool muted);
esp_err_t es8311_codec_shutdown(void);
