#include "local_connection.h"

#include <stdio.h>
#include <string.h>

#include "bringup.h"
#include "audio_output.h"
#include "ota_update.h"
#include "esp_ota_ops.h"
#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "esp_websocket_client.h"
#include "jarvis_protocol.h"
#include "wifi_provision.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define DEVICE_ID "aipi-front-door"
#define FIRMWARE_VERSION "0.9.1-wireless-ota"
#define MAX_RX_BYTES 4096
/* Audio chunks arrive as binary frames: an 8-byte header plus payload. The
 * websocket receive buffer must hold a whole maximum-size frame, otherwise the
 * client fragments it and the chunk cannot be validated as a unit. */
#define AUDIO_FRAME_HEADER_BYTES 8
#define MAX_AUDIO_FRAME_BYTES (AUDIO_FRAME_HEADER_BYTES + AUDIO_MAX_CHUNK_BYTES)
#define WS_RX_BUFFER_BYTES 8192
#define AUDIO_FRAME_MAGIC_0 'J'
#define AUDIO_FRAME_MAGIC_1 'A'

static const char *TAG = "jarvis_local";
static esp_websocket_client_handle_t client;
static bool online;
static uint16_t active_stream_id;
static uint32_t expected_sequence;
static TaskHandle_t capture_task_handle;
static volatile bool capture_stop_requested;
static uint16_t capture_stream_id;
static uint32_t capture_max_ms;
static TaskHandle_t reconnect_task_handle;

const char *local_connection_firmware_version(void) {
    return FIRMWARE_VERSION;
}

static void reconnect_task(void *arg) {
    (void)arg;
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        vTaskDelay(pdMS_TO_TICKS(5000));
        if (!client || esp_websocket_client_is_connected(client)) continue;
        ESP_LOGI(TAG, "retrying configured local Jarvis gateway");
        esp_websocket_client_stop(client);
        xTaskNotifyStateClear(NULL);
        esp_err_t result = esp_websocket_client_start(client);
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "local reconnect start failed: %s", esp_err_to_name(result));
            xTaskNotifyGive(reconnect_task_handle);
        }
    }
}

static void send_json(cJSON *root) {
    if (!client || !esp_websocket_client_is_connected(client)) {
        cJSON_Delete(root);
        return;
    }
    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!payload) return;
    size_t length = strlen(payload);
    if (length <= MAX_RX_BYTES) {
        esp_websocket_client_send_text(client, payload, length, pdMS_TO_TICKS(3000));
    }
    cJSON_free(payload);
}

static cJSON *base_message(const char *type) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "protocolVersion", JARVIS_PROTOCOL_VERSION);
    cJSON_AddStringToObject(root, "type", type);
    char id[24];
    snprintf(id, sizeof(id), "%lld", (long long)esp_timer_get_time());
    cJSON_AddStringToObject(root, "id", id);
    return root;
}

static void send_hello(void) {
    cJSON *root = base_message("DEVICE_HELLO");
    cJSON_AddStringToObject(root, "deviceId", DEVICE_ID);
    cJSON_AddStringToObject(root, "firmwareVersion", FIRMWARE_VERSION);
    cJSON *capabilities = cJSON_AddArrayToObject(root, "capabilities");
    const char *items[] = {"DISPLAY", "BUTTON", "WIFI", "LOCAL_CONNECTION",
                           "STATUS", "SPEAKER", "MICROPHONE"};
    for (size_t i = 0; i < sizeof(items) / sizeof(items[0]); ++i) {
        cJSON_AddItemToArray(capabilities, cJSON_CreateString(items[i]));
    }
    send_json(root);
}

static void send_status(void) {
    wifi_ap_record_t access_point = {0};
    int rssi = esp_wifi_sta_get_ap_info(&access_point) == ESP_OK ? access_point.rssi : -127;
    cJSON *root = base_message("DEVICE_STATUS");
    cJSON_AddNumberToObject(root, "uptimeSeconds", esp_timer_get_time() / 1000000);
    cJSON_AddNumberToObject(root, "wifiRssi", rssi);
    cJSON_AddNumberToObject(root, "freeHeap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(root, "freePsram", heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    cJSON_AddStringToObject(root, "displayStatus", online ? "ONLINE" : "OFFLINE");
    cJSON_AddStringToObject(root, "buttonStatus", "READY");
    cJSON_AddStringToObject(root, "terminalState", online ? "JARVIS_ONLINE" : "AUTHENTICATING");
    cJSON_AddStringToObject(root, "otaSlot", ota_update_running_slot());
    cJSON_AddBoolToObject(root, "otaPendingVerify", ota_update_pending_verify());
    send_json(root);
}

/* Reassembles and plays one binary audio frame.
 *
 * esp_websocket_client delivers a payload in fragments whenever the frame does
 * not arrive in a single read, which happens routinely once a stream runs for
 * more than a few seconds. Rejecting fragments outright truncated long
 * utterances part-way through, so fragments are accumulated into a fixed
 * buffer sized for one maximum frame. The buffer is static and bounded: no
 * allocation, and a stream cannot grow device memory however long Jarvis
 * speaks.
 *
 * Every rejection aborts the stream rather than skipping the chunk: silently
 * dropping a chunk would emit a glitch and desynchronise the sequence, and a
 * stream already known malformed has no claim on the amplifier. */
static uint8_t audio_frame[MAX_AUDIO_FRAME_BYTES];
static size_t audio_frame_filled;

static void audio_frame_fail(const char *reason) {
    audio_playback_abort(reason);
    active_stream_id = 0;
    audio_frame_filled = 0;
}

static void process_audio_frame(esp_websocket_event_data_t *event,
                                const uint8_t *data) {
    if (!audio_playback_active() || active_stream_id == 0) return;
    if (event->payload_len < AUDIO_FRAME_HEADER_BYTES + 2 ||
        event->payload_len > MAX_AUDIO_FRAME_BYTES) {
        audio_frame_fail("frame_bounds");
        return;
    }
    /* A fragment must continue exactly where the previous one ended; anything
     * else means frames have interleaved and the stream is no longer trusted. */
    if (event->payload_offset == 0) audio_frame_filled = 0;
    if ((size_t)event->payload_offset != audio_frame_filled) {
        audio_frame_fail("frame_desync");
        return;
    }
    if (audio_frame_filled + event->data_len > MAX_AUDIO_FRAME_BYTES) {
        audio_frame_fail("frame_bounds");
        return;
    }
    memcpy(audio_frame + audio_frame_filled, data, event->data_len);
    audio_frame_filled += event->data_len;
    if (audio_frame_filled < (size_t)event->payload_len) return;  /* incomplete */

    size_t frame_len = audio_frame_filled;
    audio_frame_filled = 0;

    if (audio_frame[0] != AUDIO_FRAME_MAGIC_0 || audio_frame[1] != AUDIO_FRAME_MAGIC_1) {
        audio_frame_fail("bad_magic");
        return;
    }
    uint16_t stream_id = (uint16_t)(audio_frame[2] | (audio_frame[3] << 8));
    uint32_t sequence = (uint32_t)audio_frame[4] | ((uint32_t)audio_frame[5] << 8) |
                        ((uint32_t)audio_frame[6] << 16) | ((uint32_t)audio_frame[7] << 24);
    if (stream_id != active_stream_id) {
        audio_frame_fail("stream_id_mismatch");
        return;
    }
    if (sequence != expected_sequence) {
        audio_frame_fail("sequence_gap");
        return;
    }
    expected_sequence++;
    if (audio_playback_write(audio_frame + AUDIO_FRAME_HEADER_BYTES,
                             frame_len - AUDIO_FRAME_HEADER_BYTES) != ESP_OK) {
        active_stream_id = 0;
        audio_frame_filled = 0;
    }
}

/* Streams bounded microphone audio to Jarvis.
 *
 * Runs as its own task because i2s_channel_read blocks; doing this in the
 * websocket event handler would stall the connection. Capture is bounded by
 * capture_max_ms and by an explicit stop, and the microphone is always torn
 * down on the way out, including on send failure, so the ADC is never left
 * live because a message was missed. Nothing is buffered beyond one chunk. */
/* Static rather than on the task stack. Together these buffers are about 2 KB,
 * which overflowed a 4 KB task stack and rebooted the device the first time
 * capture ran. Only one capture task ever exists, guarded by capture_task_handle
 * and by the shared playback lock, so static storage is safe and keeps the
 * footprint fixed instead of stack-dependent. */
static uint8_t capture_chunk[AUDIO_MIC_CHUNK_BYTES];
static uint8_t capture_frame[AUDIO_FRAME_HEADER_BYTES + AUDIO_MIC_CHUNK_BYTES];

/* Reports actual end-of-playback to Jarvis. Runs on the audio path, so it only
 * queues a small control message and does no work of its own. */
static void on_playback_finished(uint32_t bytes, const char *reason) {
    cJSON *done = base_message("AUDIO_DONE");
    cJSON_AddNumberToObject(done, "bytes", bytes);
    cJSON_AddStringToObject(done, "reason", reason ? reason : "complete");
    send_json(done);
}

/* Reports OTA progress to Jarvis and to the physical display.
 *
 * The display deliberately shows only state and percentage: no URLs, no
 * credentials, nothing that would leak if someone photographed the door. */
/* Confirms a freshly installed image, but only after it has proved itself.
 *
 * Reaching an authenticated Jarvis connection already demonstrates that boot,
 * PSRAM, display, Wi-Fi and the gateway handshake all work. The task then
 * waits out a health window before marking the image valid, so a build that
 * boots and then panics or watchdogs is never confirmed and the bootloader
 * rolls back on the next reset. */
#define OTA_HEALTH_WINDOW_MS 30000

/* Deliberately fails confirmation, for exercising rollback.
 *
 * Enabled only by building with -DJARVIS_OTA_ROLLBACK_TEST=1. The image boots
 * and runs normally, then asks the bootloader to roll back using the supported
 * ESP-IDF call rather than crashing, so the test can never leave the device in
 * a boot loop. */
static void ota_confirm_task(void *unused) {
    (void)unused;
    vTaskDelay(pdMS_TO_TICKS(OTA_HEALTH_WINDOW_MS));
#if defined(JARVIS_OTA_ROLLBACK_TEST) && JARVIS_OTA_ROLLBACK_TEST
    ESP_LOGW(TAG, "ROLLBACK TEST build: refusing to confirm this image");
    cJSON *notice = base_message("OTA_STATUS");
    cJSON_AddStringToObject(notice, "state", "ROLLED_BACK");
    cJSON_AddNumberToObject(notice, "percent", 0);
    cJSON_AddStringToObject(notice, "detail", "rollback_test_build");
    send_json(notice);
    bringup_display_status("JARVIS", "ROLLING BACK", FIRMWARE_VERSION);
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_ota_mark_app_invalid_rollback_and_reboot();
    vTaskDelete(NULL);
    return;
#endif
    if (!online) {
        /* Connection lost during the window: do not confirm. A reset now rolls
         * back to the previous image. */
        ESP_LOGW(TAG, "OTA health window ended OFFLINE; leaving image unconfirmed");
        vTaskDelete(NULL);
        return;
    }
    esp_err_t result = ota_update_mark_valid();
    ESP_LOGI(TAG, "OTA image confirmed after health window: %s",
             esp_err_to_name(result));
    cJSON *message = base_message("OTA_STATUS");
    cJSON_AddStringToObject(message, "state", "SUCCEEDED");
    cJSON_AddNumberToObject(message, "percent", 100);
    cJSON_AddStringToObject(message, "detail", "health_window_passed");
    send_json(message);
    vTaskDelete(NULL);
}

static void ota_report(const char *state, int percent, const char *detail) {
    cJSON *message = base_message("OTA_STATUS");
    cJSON_AddStringToObject(message, "state", state);
    cJSON_AddNumberToObject(message, "percent", percent);
    if (detail) cJSON_AddStringToObject(message, "detail", detail);
    send_json(message);

    char line[24];
    if (!strcmp(state, "DOWNLOADING")) {
        snprintf(line, sizeof(line), "UPDATING %d%%", percent);
    } else if (!strcmp(state, "VERIFYING")) {
        snprintf(line, sizeof(line), "VERIFYING");
    } else if (!strcmp(state, "REBOOTING")) {
        snprintf(line, sizeof(line), "RESTARTING");
    } else {
        snprintf(line, sizeof(line), "UPDATE FAILED");
    }
    bringup_display_status("JARVIS", line, FIRMWARE_VERSION);
}

static void capture_task(void *unused) {
    (void)unused;
    uint8_t *chunk = capture_chunk;
    uint8_t *frame = capture_frame;
    uint32_t sequence = 0;
    uint32_t sent_bytes = 0;
    const uint32_t max_bytes =
        (AUDIO_SAMPLE_RATE_HZ * (AUDIO_BITS_PER_SAMPLE / 8)) / 1000 * capture_max_ms;
    TickType_t started = xTaskGetTickCount();
    const char *reason = "complete";

    esp_err_t result = audio_input_begin();
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "microphone start failed: %s", esp_err_to_name(result));
        cJSON *failed = base_message("MIC_ABORT");
        cJSON_AddNumberToObject(failed, "streamId", capture_stream_id);
        cJSON_AddStringToObject(failed, "reason", esp_err_to_name(result));
        send_json(failed);
        capture_task_handle = NULL;
        vTaskDelete(NULL);
        return;
    }

    cJSON *begin = base_message("MIC_BEGIN");
    cJSON_AddNumberToObject(begin, "streamId", capture_stream_id);
    cJSON_AddNumberToObject(begin, "sampleRate", AUDIO_SAMPLE_RATE_HZ);
    cJSON_AddNumberToObject(begin, "channels", AUDIO_CHANNELS);
    cJSON_AddNumberToObject(begin, "bitsPerSample", AUDIO_BITS_PER_SAMPLE);
    send_json(begin);

    while (!capture_stop_requested && sent_bytes < max_bytes) {
        if ((xTaskGetTickCount() - started) > pdMS_TO_TICKS(capture_max_ms)) {
            reason = "duration_limit";
            break;
        }
        size_t got = 0;
        int64_t t0 = esp_timer_get_time();
        if (audio_input_read(chunk, AUDIO_MIC_CHUNK_BYTES, &got, 500) != ESP_OK ||
            got == 0) {
            reason = "read_failed";
            break;
        }
        int64_t t1 = esp_timer_get_time();
        frame[0] = AUDIO_FRAME_MAGIC_0;
        frame[1] = AUDIO_FRAME_MAGIC_1;
        frame[2] = (uint8_t)(capture_stream_id & 0xFF);
        frame[3] = (uint8_t)(capture_stream_id >> 8);
        frame[4] = (uint8_t)(sequence & 0xFF);
        frame[5] = (uint8_t)((sequence >> 8) & 0xFF);
        frame[6] = (uint8_t)((sequence >> 16) & 0xFF);
        frame[7] = (uint8_t)((sequence >> 24) & 0xFF);
        memcpy(frame + AUDIO_FRAME_HEADER_BYTES, chunk, got);
        int written = esp_websocket_client_send_bin(
            client, (const char *)frame, (int)(AUDIO_FRAME_HEADER_BYTES + got),
            pdMS_TO_TICKS(1000));
        if (written < 0) {
            reason = "send_failed";
            break;
        }
        int64_t t2 = esp_timer_get_time();
        if (sequence < 4) {
            ESP_LOGD(TAG, "capture timing seq=%lu got=%u read=%lldus send=%lldus",
                     (unsigned long)sequence, (unsigned)got,
                     (long long)(t1 - t0), (long long)(t2 - t1));
        }
        sequence++;
        sent_bytes += got;
    }
    if (capture_stop_requested) reason = "stopped";

    audio_input_end();
    cJSON *end = base_message("MIC_END");
    cJSON_AddNumberToObject(end, "streamId", capture_stream_id);
    cJSON_AddNumberToObject(end, "totalChunks", sequence);
    cJSON_AddNumberToObject(end, "totalBytes", sent_bytes);
    cJSON_AddStringToObject(end, "reason", reason);
    send_json(end);
    ESP_LOGI(TAG, "microphone stream END bytes=%lu reason=%s",
             (unsigned long)sent_bytes, reason);
    capture_task_handle = NULL;
    vTaskDelete(NULL);
}

static void process_control(const char *data, int length) {
    cJSON *root = cJSON_ParseWithLength(data, length);
    if (!root) return;
    cJSON *version = cJSON_GetObjectItemCaseSensitive(root, "protocolVersion");
    cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    if (!cJSON_IsNumber(version) || version->valueint != JARVIS_PROTOCOL_VERSION ||
        !cJSON_IsString(type)) {
        cJSON_Delete(root);
        return;
    }
    if (!strcmp(type->valuestring, "DEVICE_READY")) {
        online = true;
        audio_output_set_manual_test_enabled(true);
        bringup_display_status4("JARVIS", "WI-FI: OK", "JARVIS: ONLINE", FIRMWARE_VERSION);
        ESP_LOGI(TAG, "authenticated local connection ONLINE");
        send_status();
        if (ota_update_pending_verify()) {
            ESP_LOGW(TAG, "running a freshly installed image; starting health window");
            bringup_display_status4("JARVIS", "WI-FI: OK", "VERIFYING UPDATE",
                                    FIRMWARE_VERSION);
            xTaskCreate(ota_confirm_task, "aipi_ota_ok", 3072, NULL, 4, NULL);
        }
    } else if (!strcmp(type->valuestring, "PING")) {
        cJSON *reply = base_message("PONG");
        cJSON *id = cJSON_GetObjectItemCaseSensitive(root, "id");
        if (cJSON_IsString(id)) cJSON_AddStringToObject(reply, "replyTo", id->valuestring);
        send_json(reply);
    } else if (!strcmp(type->valuestring, "STATUS_REQUEST")) {
        send_status();
    } else if (!strcmp(type->valuestring, "AUDIO_BEGIN")) {
        /* Playback is only ever accepted on an authenticated session that has
         * completed the DEVICE_READY handshake. */
        if (!online) {
            ESP_LOGW(TAG, "AUDIO_BEGIN rejected: session not ready");
        } else {
            cJSON *rate = cJSON_GetObjectItemCaseSensitive(root, "sampleRate");
            cJSON *channels = cJSON_GetObjectItemCaseSensitive(root, "channels");
            cJSON *bits = cJSON_GetObjectItemCaseSensitive(root, "bitsPerSample");
            cJSON *expected = cJSON_GetObjectItemCaseSensitive(root, "expectedBytes");
            cJSON *stream = cJSON_GetObjectItemCaseSensitive(root, "streamId");
            if (!cJSON_IsNumber(rate) || !cJSON_IsNumber(channels) ||
                !cJSON_IsNumber(bits) || !cJSON_IsNumber(stream) ||
                stream->valueint <= 0 || stream->valueint > 0xFFFF) {
                ESP_LOGW(TAG, "AUDIO_BEGIN rejected: malformed");
            } else {
                active_stream_id = stream->valueint;
                expected_sequence = 0;
                audio_frame_filled = 0;
                esp_err_t result = audio_playback_begin(
                    (uint32_t)rate->valueint, (uint8_t)channels->valueint,
                    (uint8_t)bits->valueint,
                    cJSON_IsNumber(expected) ? (uint32_t)expected->valuedouble : 0);
                if (result != ESP_OK) {
                    active_stream_id = 0;
                    ESP_LOGW(TAG, "AUDIO_BEGIN rejected: %s", esp_err_to_name(result));
                }
            }
        }
    } else if (!strcmp(type->valuestring, "AUDIO_END")) {
        active_stream_id = 0;
        audio_playback_end();
    } else if (!strcmp(type->valuestring, "AUDIO_ABORT")) {
        active_stream_id = 0;
        audio_playback_abort("gateway_abort");
    } else if (!strcmp(type->valuestring, "LISTEN_START")) {
        cJSON *stream = cJSON_GetObjectItemCaseSensitive(root, "streamId");
        cJSON *max_ms = cJSON_GetObjectItemCaseSensitive(root, "maxMilliseconds");
        if (!online) {
            ESP_LOGW(TAG, "LISTEN_START rejected: session not ready");
        } else if (audio_playback_active()) {
            /* Half-duplex: never open the microphone while the amplifier is
             * driving the speaker, whatever the host believes. */
            ESP_LOGW(TAG, "LISTEN_START rejected: speaker active");
        } else if (capture_task_handle) {
            ESP_LOGW(TAG, "LISTEN_START rejected: already capturing");
        } else if (!cJSON_IsNumber(stream) || stream->valueint <= 0 ||
                   stream->valueint > 0xFFFF) {
            ESP_LOGW(TAG, "LISTEN_START rejected: malformed");
        } else {
            capture_stream_id = (uint16_t)stream->valueint;
            capture_max_ms = cJSON_IsNumber(max_ms)
                ? (uint32_t)max_ms->valuedouble : AUDIO_MIC_DEFAULT_MS;
            if (capture_max_ms > AUDIO_MIC_MAX_MS) capture_max_ms = AUDIO_MIC_MAX_MS;
            capture_stop_requested = false;
            if (xTaskCreate(capture_task, "aipi_capture", 6144, NULL, 5,
                            &capture_task_handle) != pdPASS) {
                capture_task_handle = NULL;
                ESP_LOGE(TAG, "LISTEN_START failed: no memory for capture task");
            }
        }
    } else if (!strcmp(type->valuestring, "LISTEN_STOP")) {
        capture_stop_requested = true;
    } else if (!strcmp(type->valuestring, "OTA_OFFER")) {
        /* Firmware replacement is the most privileged operation here, so it is
         * refused unless the session is authenticated and the device is idle. */
        if (!online) {
            ESP_LOGW(TAG, "OTA_OFFER rejected: session not ready");
        } else if (audio_playback_active() || audio_input_active() ||
                   capture_task_handle) {
            ESP_LOGW(TAG, "OTA_OFFER rejected: audio in progress");
            ota_report("FAILED", 0, "audio_in_progress");
        } else {
            esp_err_t result = ota_update_handle_offer(root, ota_report);
            if (result != ESP_OK) {
                ESP_LOGW(TAG, "OTA_OFFER rejected: %s", esp_err_to_name(result));
            }
        }
    }
    cJSON_Delete(root);
}

static void websocket_event(void *arg, esp_event_base_t base, int32_t event_id, void *data) {
    (void)arg;
    (void)base;
    esp_websocket_event_data_t *event = data;
    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        online = false;
        audio_playback_abort("reconnected");
        active_stream_id = 0;
        audio_frame_filled = 0;
        audio_output_set_manual_test_enabled(false);
        bringup_display_status("JARVIS", "WI-FI: OK", "AUTHENTICATING");
        send_hello();
    } else if (event_id == WEBSOCKET_EVENT_DATA && event->op_code == 1 &&
               event->payload_len <= MAX_RX_BYTES && event->payload_offset == 0 &&
               event->data_len == event->payload_len) {
        process_control(event->data_ptr, event->data_len);
    } else if (event_id == WEBSOCKET_EVENT_DATA && event->op_code == 2) {
        process_audio_frame(event, (const uint8_t *)event->data_ptr);
    } else if (event_id == WEBSOCKET_EVENT_DISCONNECTED || event_id == WEBSOCKET_EVENT_CLOSED ||
               event_id == WEBSOCKET_EVENT_ERROR) {
        if (online) ESP_LOGW(TAG, "local Jarvis connection OFFLINE; reconnecting");
        /* A dropped connection mid-utterance must never leave the amplifier
         * enabled waiting for chunks that will never arrive. */
        audio_playback_abort("connection_lost");
        /* Close the microphone too. A dead socket must not leave the ADC live
         * streaming into a connection that no longer exists. */
        capture_stop_requested = true;
        active_stream_id = 0;
        audio_frame_filled = 0;
        online = false;
        bringup_display_status("JARVIS", "WI-FI: OK", "JARVIS: OFFLINE");
        if (reconnect_task_handle) xTaskNotifyGive(reconnect_task_handle);
    }
}

bool local_connection_button_pressed(void) {
    /* Only meaningful on an authenticated session. Offline, the caller keeps
     * its local behaviour rather than silently doing nothing. */
    if (!online) return false;
    cJSON *pressed = base_message("BUTTON_PRESSED");
    send_json(pressed);
    ESP_LOGI(TAG, "button press reported to Jarvis");
    return true;
}

esp_err_t local_connection_start(void) {
    jarvis_local_config_t provisioned;
    if (!wifi_provision_load_jarvis_config(&provisioned)) {
        ESP_LOGW(TAG, "local Jarvis configuration missing; use setup recovery");
        bringup_display_status("JARVIS", "WI-FI: OK", "JARVIS: SETUP");
        return ESP_ERR_NOT_FOUND;
    }
    char uri[128];
    snprintf(uri, sizeof(uri), "ws://%s:%u/ws/device", provisioned.host, provisioned.port);
    esp_websocket_client_config_t config = {
        .uri = uri,
        .subprotocol = "jarvis.device.v1",
        .disable_auto_reconnect = true,
        .reconnect_timeout_ms = 5000,
        .network_timeout_ms = 5000,
        .buffer_size = WS_RX_BUFFER_BYTES,
        .ping_interval_sec = 30,
        .pingpong_timeout_sec = 75,
        .keep_alive_enable = true,
        .keep_alive_idle = 30,
        .keep_alive_interval = 10,
        .keep_alive_count = 3,
    };
    client = esp_websocket_client_init(&config);
    if (!client) return ESP_ERR_NO_MEM;
    char authorization[96];
    snprintf(authorization, sizeof(authorization), "DevicePassword %s",
             provisioned.device_password);
    esp_err_t result = esp_websocket_client_append_header(client, "Authorization", authorization);
    memset(authorization, 0, sizeof(authorization));
    memset(provisioned.device_password, 0, sizeof(provisioned.device_password));
    if (result != ESP_OK) return result;
    audio_playback_set_finished_callback(on_playback_finished);
    ESP_ERROR_CHECK(esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, websocket_event, NULL));
    if (xTaskCreate(reconnect_task, "jarvis_reconnect", 4096, NULL, 5,
                    &reconnect_task_handle) != pdPASS) {
        esp_websocket_client_destroy(client);
        client = NULL;
        return ESP_ERR_NO_MEM;
    }
    bringup_display_status("JARVIS", "WI-FI: OK", "JARVIS: CONNECTING");
    ESP_LOGI(TAG, "connecting to configured local Jarvis gateway (credential omitted)");
    return esp_websocket_client_start(client);
}
