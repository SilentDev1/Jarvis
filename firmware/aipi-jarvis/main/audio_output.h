#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

/* Canonical local audio format. Mirrored by
 * src/jarvis_home/devices/audio_stream.py; the two must not drift. */
#define AUDIO_SAMPLE_RATE_HZ 16000
#define AUDIO_CHANNELS 1
#define AUDIO_BITS_PER_SAMPLE 16
#define AUDIO_MAX_CHUNK_BYTES 4096
#define AUDIO_MAX_STREAM_SECONDS 30
#define AUDIO_MAX_STREAM_BYTES \
    (AUDIO_SAMPLE_RATE_HZ * AUDIO_CHANNELS * (AUDIO_BITS_PER_SAMPLE / 8) * \
     AUDIO_MAX_STREAM_SECONDS)
/* A stalled stream must never hold the amplifier open. */
#define AUDIO_STREAM_TIMEOUT_MS 10000

esp_err_t audio_output_prepare(void);
esp_err_t audio_output_test_tone(void);
void audio_output_set_manual_test_enabled(bool enabled);
bool audio_output_manual_test_enabled(void);

/* Bounded streaming playback.
 *
 * The amplifier is enabled by begin() and is guaranteed to be disabled again by
 * end(), by abort(), by any failing write, and by the stall watchdog. Callers
 * do not touch GPIO9 directly. */
esp_err_t audio_playback_begin(uint32_t sample_rate, uint8_t channels,
                               uint8_t bits_per_sample, uint32_t expected_bytes);
esp_err_t audio_playback_write(const uint8_t *pcm, size_t bytes);
esp_err_t audio_playback_end(void);
void audio_playback_abort(const char *reason);
bool audio_playback_active(void);

/* Aborts a stream that has stalled mid-flight, so a wedged sender cannot leave
 * the amplifier enabled. Safe to call when no stream is active. */
void audio_playback_poll_timeout(void);
