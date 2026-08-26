#include "aipi_board.h"
#include "bringup.h"
#include "arc_light.h"
#include "display_controller.h"
#include "audio_output.h"
#include "esp_chip_info.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_flash.h"
#include "nvs_flash.h"
#include "local_connection.h"
#include "terminal_state.h"
#include "wifi_provision.h"

static const char *TAG = "jarvis_aipi";

/* Hold the board's own power on.
 *
 * Done first, before logging or NVS, because on battery the latch only stays
 * closed while the power button is held. Anything slow ahead of this risks the
 * rails dropping before the pin is asserted. */
static void hold_board_power(void) {
    gpio_config_t latch = {
        .pin_bit_mask = 1ULL << AIPI_POWER_LATCH,
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&latch);
    gpio_set_level(AIPI_POWER_LATCH, 1);
}

void app_main(void) {
    hold_board_power();
    terminal_state_t state = TERMINAL_BOOTING;
    esp_chip_info_t chip;
    uint32_t flash_size = 0;
    esp_chip_info(&chip);
    esp_flash_get_size(NULL, &flash_size);
    ESP_LOGI(TAG, "Jarvis AiPi %s", local_connection_firmware_version());
    ESP_LOGI(TAG, "chip=ESP32-S3 revision=%d cores=%d flash=%luMB", chip.revision,
             chip.cores, (unsigned long)(flash_size / (1024 * 1024)));
    ESP_LOGI(TAG, "PSRAM total=%u free=%u", heap_caps_get_total_size(MALLOC_CAP_SPIRAM),
             heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    ESP_LOGI(TAG, "GPIO10 power latch asserted HIGH (battery rails held)");
    /* Best effort. If the interface cannot start the device still runs and
     * falls back to the plain text screens. */
    if (display_controller_start() == ESP_OK) {
        display_controller_set(JARVIS_VISUAL_BOOT);
    }
    /* Onboard WS2812. Initialised so it is ready, but left disabled: a light
     * at a front door switching itself on is the owner's decision. */
    arc_light_init(ARC_BACKEND_ONBOARD);
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "initializing custom NVS partition; factory NVS at 0x9000 is untouched");
        result = nvs_flash_erase_partition("nvs");
        if (result == ESP_OK) result = nvs_flash_init();
        state = result == ESP_OK ? TERMINAL_CONNECTING : TERMINAL_ERROR;
    } else if (result != ESP_OK) {
        ESP_LOGE(TAG, "NVS initialization failed: %s", esp_err_to_name(result));
        state = TERMINAL_ERROR;
    } else {
        state = TERMINAL_CONNECTING;
    }
    bool display_ready = bringup_display_init() == ESP_OK;
    bool button_ready = bringup_button_start() == ESP_OK;
    bool codec_ready = bringup_codec_probe();
    bool audio_ready = codec_ready && audio_output_prepare() == ESP_OK;
    if (display_ready) {
        bringup_display_status("JARVIS", "BRING-UP 0.1.0",
                               audio_ready ? "AUDIO: READY" : "AUDIO: FAIL");
    }
    ESP_LOGI(TAG, "state=%s display=%s button=%s codec=%s audio=%s", terminal_state_name(state),
             display_ready ? "PASS" : "FAIL", button_ready ? "PASS" : "FAIL",
             codec_ready ? "PASS" : "FAIL", audio_ready ? "PASS" : "FAIL");
    if (result == ESP_OK && wifi_provision_boot_reset_requested()) {
        ESP_ERROR_CHECK(wifi_provision_clear_custom_config());
    }
    if (result == ESP_OK) {
        esp_err_t wifi_result = wifi_provision_start();
        if (wifi_result != ESP_OK) {
            ESP_LOGE(TAG, "Wi-Fi provisioning failed: %s", esp_err_to_name(wifi_result));
            bringup_display_status("JARVIS", "WI-FI ERROR", "CHECK SERIAL");
        } else if (wifi_provision_status().connected) {
            esp_err_t local_result = local_connection_start();
            if (local_result != ESP_OK && local_result != ESP_ERR_NOT_FOUND) {
                ESP_LOGE(TAG, "Local Jarvis connection failed to start: %s",
                         esp_err_to_name(local_result));
            }
        }
    }
}
