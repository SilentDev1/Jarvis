#include "local_connection.h"

#include <stdio.h>
#include <string.h>

#include "bringup.h"
#include "audio_output.h"
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
#define FIRMWARE_VERSION "0.3.2-audio-watchdog"
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
static TaskHandle_t reconnect_task_handle;

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
    const char *items[] = {"DISPLAY", "BUTTON", "WIFI", "LOCAL_CONNECTION", "STATUS"};
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
        active_stream_id = 0;
        audio_frame_filled = 0;
        online = false;
        bringup_display_status("JARVIS", "WI-FI: OK", "JARVIS: OFFLINE");
        if (reconnect_task_handle) xTaskNotifyGive(reconnect_task_handle);
    }
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
