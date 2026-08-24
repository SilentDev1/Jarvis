#include "esp_log.h"
#include "nvs_flash.h"
#include "terminal_state.h"

static const char *TAG = "jarvis_aipi";

void app_main(void) {
    terminal_state_t state = TERMINAL_BOOTING;
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGE(TAG, "NVS requires recovery; refusing automatic erase");
        state = TERMINAL_ERROR;
    } else if (result != ESP_OK) {
        ESP_LOGE(TAG, "NVS initialization failed: %s", esp_err_to_name(result));
        state = TERMINAL_ERROR;
    } else {
        state = TERMINAL_CONNECTING;
    }
    ESP_LOGI(TAG, "Jarvis AiPi 0.1.0 state=%s", terminal_state_name(state));
    ESP_LOGW(TAG, "Hardware drivers intentionally disabled until pins are physically verified");
}
