#include "audio_output.h"

#include <math.h>
#include <stdint.h>

#include "aipi_board.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "es8311_codec.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#define SAMPLE_RATE 16000
#define CHUNK_SAMPLES 256
#define TONE_FREQUENCY_HZ 880
#define TONE_DURATION_MS 400
#define TONE_AMPLITUDE 16000

static const char *TAG = "jarvis_audio";
static i2s_chan_handle_t tx_channel;
static SemaphoreHandle_t playback_lock;
static bool initialized;
static bool playing;
static volatile bool manual_test_enabled;

void audio_output_set_manual_test_enabled(bool enabled) {
    manual_test_enabled = enabled;
}

bool audio_output_manual_test_enabled(void) {
    return manual_test_enabled;
}

static void amplifier_set(bool enabled) {
    gpio_set_level(AIPI_SPEAKER_ENABLE, enabled ? 1 : 0);
    ESP_LOGI(TAG, "speaker amplifier %s", enabled ? "ENABLED" : "DISABLED");
}

static esp_err_t initialize(void) {
    if (initialized) return ESP_OK;
    if (!playback_lock) playback_lock = xSemaphoreCreateMutex();
    ESP_RETURN_ON_FALSE(playback_lock, ESP_ERR_NO_MEM, TAG, "playback mutex");
    gpio_config_t amp_config = {
        .pin_bit_mask = 1ULL << AIPI_SPEAKER_ENABLE,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&amp_config), TAG, "amp GPIO");
    amplifier_set(false);

    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(
        I2S_NUM_0, I2S_ROLE_MASTER);
    channel_config.auto_clear = true;
    esp_err_t result = i2s_new_channel(&channel_config, &tx_channel, NULL);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "I2S channel init failed: %s", esp_err_to_name(result));
        return result;
    }
    i2s_std_config_t standard_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = AIPI_AUDIO_MCLK,
            .bclk = AIPI_AUDIO_BCLK,
            .ws = AIPI_AUDIO_WS,
            .dout = AIPI_AUDIO_DOUT,
            .din = I2S_GPIO_UNUSED,
        },
    };
    standard_config.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    result = i2s_channel_init_std_mode(tx_channel, &standard_config);
    if (result != ESP_OK) return result;
    result = i2s_channel_enable(tx_channel);
    if (result != ESP_OK) return result;
    result = es8311_codec_initialize_output();
    esp_err_t disable_result = i2s_channel_disable(tx_channel);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "codec output init failed safely: %s", esp_err_to_name(result));
        return result;
    }
    if (disable_result != ESP_OK) return disable_result;
    initialized = true;
    ESP_LOGI(TAG, "I2S TX ready MCLK=GPIO6 BCLK=GPIO14 WS=GPIO12 DOUT=GPIO11");
    return ESP_OK;
}

esp_err_t audio_output_prepare(void) {
    return initialize();
}

static esp_err_t start(void) {
    ESP_RETURN_ON_ERROR(initialize(), TAG, "speaker initialize");
    ESP_RETURN_ON_FALSE(xSemaphoreTake(playback_lock, 0) == pdTRUE,
                        ESP_ERR_INVALID_STATE, TAG, "speaker busy");
    esp_err_t result = i2s_channel_enable(tx_channel);
    if (result != ESP_OK) goto fail;
    result = es8311_codec_set_muted(true);
    if (result != ESP_OK) goto fail;
    amplifier_set(true);
    vTaskDelay(pdMS_TO_TICKS(10));
    result = es8311_codec_set_muted(false);
    if (result != ESP_OK) goto fail;
    playing = true;
    return ESP_OK;
fail:
    amplifier_set(false);
    i2s_channel_disable(tx_channel);
    xSemaphoreGive(playback_lock);
    return result;
}

static esp_err_t write_mono(const int16_t *samples, size_t count) {
    ESP_RETURN_ON_FALSE(playing && samples && count <= CHUNK_SAMPLES,
                        ESP_ERR_INVALID_ARG, TAG, "invalid audio chunk");
    int16_t stereo[CHUNK_SAMPLES * 2];
    for (size_t i = 0; i < count; ++i) {
        stereo[i * 2] = samples[i];
        stereo[i * 2 + 1] = samples[i];
    }
    size_t written = 0;
    size_t requested = count * 2 * sizeof(int16_t);
    ESP_RETURN_ON_ERROR(i2s_channel_write(tx_channel, stereo, requested, &written,
                                          pdMS_TO_TICKS(1000)), TAG, "I2S write");
    return written == requested ? ESP_OK : ESP_ERR_INVALID_SIZE;
}

static void stop(void) {
    if (!playing) return;
    es8311_codec_set_muted(true);
    vTaskDelay(pdMS_TO_TICKS(5));
    amplifier_set(false);
    i2s_channel_disable(tx_channel);
    playing = false;
    xSemaphoreGive(playback_lock);
}

esp_err_t audio_output_test_tone(void) {
    ESP_RETURN_ON_ERROR(start(), TAG, "tone start");
    ESP_LOGI(TAG, "one-shot low-volume speaker tone START");
    const size_t total = SAMPLE_RATE * TONE_DURATION_MS / 1000;
    int16_t samples[CHUNK_SAMPLES];
    esp_err_t result = ESP_OK;
    for (size_t offset = 0; offset < total;) {
        size_t count = total - offset;
        if (count > CHUNK_SAMPLES) count = CHUNK_SAMPLES;
        for (size_t i = 0; i < count; ++i) {
            float phase = 2.0f * (float)M_PI * TONE_FREQUENCY_HZ *
                          (float)(offset + i) / SAMPLE_RATE;
            samples[i] = (int16_t)(sinf(phase) * TONE_AMPLITUDE);
        }
        result = write_mono(samples, count);
        if (result != ESP_OK) break;
        offset += count;
    }
    int16_t silence[CHUNK_SAMPLES] = {0};
    if (result == ESP_OK) result = write_mono(silence, CHUNK_SAMPLES);
    vTaskDelay(pdMS_TO_TICKS(25));
    stop();
    ESP_LOGI(TAG, "one-shot speaker tone END result=%s", esp_err_to_name(result));
    return result;
}
