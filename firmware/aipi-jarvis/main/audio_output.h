#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t audio_output_test_tone(void);
esp_err_t audio_output_prepare(void);
void audio_output_set_manual_test_enabled(bool enabled);
bool audio_output_manual_test_enabled(void);
