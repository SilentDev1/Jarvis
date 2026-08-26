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
static i2s_chan_handle_t rx_channel;
static bool capturing;
static audio_playback_finished_fn audio_playback_finished_cb;

void audio_playback_set_finished_callback(audio_playback_finished_fn callback) {
    audio_playback_finished_cb = callback;
}
static SemaphoreHandle_t playback_lock;
static bool initialized;
static bool playing;
static volatile bool manual_test_enabled;
static bool streaming;
static uint32_t stream_expected_bytes;
static uint32_t stream_written_bytes;
static TickType_t stream_last_write_tick;

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
    /* Allocate RX alongside TX. The known-working AiPi Lite reference does the
     * same, and allocating both once at startup avoids touching GDMA later
     * while audio is live. RX stays disabled until capture is requested. */
    esp_err_t result = i2s_new_channel(&channel_config, &tx_channel, &rx_channel);
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
            .din = AIPI_AUDIO_DIN,
        },
    };
    standard_config.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    result = i2s_channel_init_std_mode(tx_channel, &standard_config);
    if (result != ESP_OK) return result;
    result = i2s_channel_init_std_mode(rx_channel, &standard_config);
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

/* ---------------------------------------------------------------------------
 * Bounded streaming playback
 *
 * write_mono() above is reused unchanged so that streamed audio travels the
 * exact signal path that was physically validated by the test tone.
 * ------------------------------------------------------------------------- */

bool audio_playback_active(void) {
    return streaming;
}

static void stream_reset(void) {
    streaming = false;
    stream_expected_bytes = 0;
    stream_written_bytes = 0;
}

esp_err_t audio_playback_begin(uint32_t sample_rate, uint8_t channels,
                               uint8_t bits_per_sample, uint32_t expected_bytes) {
    /* Only the canonical format is accepted. Silently resampling or accepting a
     * format the codec is not configured for would produce noise at full
     * amplifier gain. */
    if (sample_rate != AUDIO_SAMPLE_RATE_HZ || channels != AUDIO_CHANNELS ||
        bits_per_sample != AUDIO_BITS_PER_SAMPLE) {
        ESP_LOGW(TAG, "playback rejected: unsupported format %lu/%u/%u",
                 (unsigned long)sample_rate, channels, bits_per_sample);
        return ESP_ERR_INVALID_ARG;
    }
    if (expected_bytes > AUDIO_MAX_STREAM_BYTES) {
        ESP_LOGW(TAG, "playback rejected: stream too large (%lu bytes)",
                 (unsigned long)expected_bytes);
        return ESP_ERR_INVALID_SIZE;
    }
    if (streaming) {
        ESP_LOGW(TAG, "playback rejected: a stream is already active");
        return ESP_ERR_INVALID_STATE;
    }
    ESP_RETURN_ON_ERROR(start(), TAG, "playback start");
    streaming = true;
    stream_expected_bytes = expected_bytes;
    stream_written_bytes = 0;
    stream_last_write_tick = xTaskGetTickCount();
    ESP_LOGI(TAG, "playback START rate=%lu expected=%lu bytes",
             (unsigned long)sample_rate, (unsigned long)expected_bytes);
    return ESP_OK;
}

esp_err_t audio_playback_write(const uint8_t *pcm, size_t bytes) {
    if (!streaming) return ESP_ERR_INVALID_STATE;
    if (!pcm || bytes == 0) {
        audio_playback_abort("empty_chunk");
        return ESP_ERR_INVALID_ARG;
    }
    /* A partial sample would desynchronise every following frame. */
    if (bytes % sizeof(int16_t)) {
        audio_playback_abort("chunk_not_sample_aligned");
        return ESP_ERR_INVALID_SIZE;
    }
    if (bytes > AUDIO_MAX_CHUNK_BYTES) {
        audio_playback_abort("chunk_too_large");
        return ESP_ERR_INVALID_SIZE;
    }
    if (stream_written_bytes + bytes > AUDIO_MAX_STREAM_BYTES) {
        audio_playback_abort("stream_too_large");
        return ESP_ERR_INVALID_SIZE;
    }
    if (stream_expected_bytes &&
        stream_written_bytes + bytes > stream_expected_bytes) {
        audio_playback_abort("stream_overrun");
        return ESP_ERR_INVALID_SIZE;
    }

    /* Feed the validated writer in its fixed chunk size rather than allocating
     * a buffer proportional to the response. Memory stays bounded regardless of
     * how long Jarvis speaks. */
    const int16_t *samples = (const int16_t *)pcm;
    size_t remaining = bytes / sizeof(int16_t);
    while (remaining) {
        size_t count = remaining > CHUNK_SAMPLES ? CHUNK_SAMPLES : remaining;
        esp_err_t result = write_mono(samples, count);
        if (result != ESP_OK) {
            audio_playback_abort("i2s_write_failed");
            return result;
        }
        samples += count;
        remaining -= count;
    }
    stream_written_bytes += bytes;
    stream_last_write_tick = xTaskGetTickCount();
    return ESP_OK;
}

esp_err_t audio_playback_end(void) {
    if (!streaming) return ESP_ERR_INVALID_STATE;
    esp_err_t result = ESP_OK;
    if (stream_expected_bytes && stream_written_bytes != stream_expected_bytes) {
        ESP_LOGW(TAG, "playback underrun: %lu of %lu bytes",
                 (unsigned long)stream_written_bytes,
                 (unsigned long)stream_expected_bytes);
        result = ESP_ERR_INVALID_SIZE;
    }
    /* Flush a chunk of silence so the tail of the utterance is clocked out
     * before the amplifier is cut, otherwise the last word is truncated. */
    int16_t silence[CHUNK_SAMPLES] = {0};
    write_mono(silence, CHUNK_SAMPLES);
    vTaskDelay(pdMS_TO_TICKS(25));
    ESP_LOGI(TAG, "playback END bytes=%lu result=%s",
             (unsigned long)stream_written_bytes, esp_err_to_name(result));
    uint32_t played = stream_written_bytes;
    stream_reset();
    stop();
    /* Tell the host playback has actually finished. The host finishes sending
     * long before the device finishes playing, so without this it would leave
     * SPEAKING while the speaker is still running and could open the
     * microphone into Jarvis's own voice. */
    if (audio_playback_finished_cb) audio_playback_finished_cb(played, "complete");
    return result;
}

void audio_playback_abort(const char *reason) {
    if (!streaming) return;
    ESP_LOGW(TAG, "playback ABORT reason=%s bytes=%lu",
             reason ? reason : "unspecified",
             (unsigned long)stream_written_bytes);
    uint32_t played = stream_written_bytes;
    stream_reset();
    /* stop() mutes the codec, drops GPIO9, disables the channel and releases
     * the lock, so the amplifier is off on every abort path. */
    stop();
    if (audio_playback_finished_cb) {
        audio_playback_finished_cb(played, reason ? reason : "aborted");
    }
}

void audio_playback_poll_timeout(void) {
    if (!streaming) return;
    TickType_t elapsed = xTaskGetTickCount() - stream_last_write_tick;
    if (elapsed > pdMS_TO_TICKS(AUDIO_STREAM_TIMEOUT_MS)) {
        audio_playback_abort("stream_timeout");
    }
}

/* ---------------------------------------------------------------------------
 * Bounded microphone capture
 *
 * Capture is half-duplex by construction: it takes the same lock playback
 * uses, so the microphone can never be open while the amplifier drives the
 * speaker. Nothing is stored on the device; samples go straight to the caller.
 * ------------------------------------------------------------------------- */

bool audio_input_active(void) {
    return capturing;
}

esp_err_t audio_input_begin(void) {
    ESP_RETURN_ON_ERROR(initialize(), TAG, "capture initialize");
    if (capturing) return ESP_ERR_INVALID_STATE;
    /* Refuse if playback owns the path. This is the hardware-level half of the
     * half-duplex rule the terminal state machine enforces on the host. */
    ESP_RETURN_ON_FALSE(xSemaphoreTake(playback_lock, 0) == pdTRUE,
                        ESP_ERR_INVALID_STATE, TAG, "speaker busy");
    esp_err_t result = es8311_codec_initialize_input();
    if (result != ESP_OK) goto fail;
    /* TX and RX share BCLK and WS in full duplex, and this port is the master,
     * so the clocks only run while TX is enabled. Enabling TX with the codec
     * muted and the amplifier off gives RX a clock without producing sound. */
    result = es8311_codec_set_muted(true);
    if (result != ESP_OK) goto fail;
    amplifier_set(false);
    result = i2s_channel_enable(tx_channel);
    if (result != ESP_OK) goto fail;
    result = i2s_channel_enable(rx_channel);
    if (result != ESP_OK) {
        i2s_channel_disable(tx_channel);
        goto fail;
    }
    result = es8311_codec_set_input_muted(false);
    if (result != ESP_OK) {
        i2s_channel_disable(rx_channel);
        goto fail;
    }
    capturing = true;
    ESP_LOGI(TAG, "microphone capture START rate=%d PCM16", SAMPLE_RATE);
    return ESP_OK;
fail:
    xSemaphoreGive(playback_lock);
    return result;
}

esp_err_t audio_input_read(uint8_t *buffer, size_t bytes, size_t *out_bytes,
                           uint32_t timeout_ms) {
    ESP_RETURN_ON_FALSE(capturing && buffer && out_bytes && bytes,
                        ESP_ERR_INVALID_ARG, TAG, "invalid capture read");
    /* The codec runs stereo slots, so captured frames are stereo pairs of a
     * mono source. Read into a bounded stack buffer and keep the left channel,
     * producing the canonical mono stream without allocating. */
    /* Static for the same reason as the capture buffers: this is 1 KB, called
     * only from the single capture task, and keeping it off the stack is what
     * stops the task overflowing. */
    static int16_t stereo[CHUNK_SAMPLES * 2];
    size_t mono_wanted = bytes / sizeof(int16_t);
    if (mono_wanted > CHUNK_SAMPLES) mono_wanted = CHUNK_SAMPLES;
    size_t read_bytes = 0;
    esp_err_t result = i2s_channel_read(rx_channel, stereo,
                                        mono_wanted * 2 * sizeof(int16_t),
                                        &read_bytes, pdMS_TO_TICKS(timeout_ms));
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "I2S capture read failed: %s", esp_err_to_name(result));
        return result;
    }
    size_t frames = read_bytes / (2 * sizeof(int16_t));
    int16_t *mono = (int16_t *)buffer;
    for (size_t i = 0; i < frames; ++i) mono[i] = stereo[i * 2];
    *out_bytes = frames * sizeof(int16_t);
    return ESP_OK;
}

void audio_input_end(void) {
    if (!capturing) return;
    es8311_codec_set_input_muted(true);
    i2s_channel_disable(rx_channel);
    i2s_channel_disable(tx_channel);
    capturing = false;
    xSemaphoreGive(playback_lock);
    ESP_LOGI(TAG, "microphone capture END");
}
