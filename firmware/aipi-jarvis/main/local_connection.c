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
#define FIRMWARE_VERSION "0.2.3-speaker-clock"
#define MAX_RX_BYTES 4096

static const char *TAG = "jarvis_local";
static esp_websocket_client_handle_t client;
static bool online;
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
    }
    cJSON_Delete(root);
}

static void websocket_event(void *arg, esp_event_base_t base, int32_t event_id, void *data) {
    (void)arg;
    (void)base;
    esp_websocket_event_data_t *event = data;
    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        online = false;
        audio_output_set_manual_test_enabled(false);
        bringup_display_status("JARVIS", "WI-FI: OK", "AUTHENTICATING");
        send_hello();
    } else if (event_id == WEBSOCKET_EVENT_DATA && event->op_code == 1 &&
               event->payload_len <= MAX_RX_BYTES && event->payload_offset == 0 &&
               event->data_len == event->payload_len) {
        process_control(event->data_ptr, event->data_len);
    } else if (event_id == WEBSOCKET_EVENT_DISCONNECTED || event_id == WEBSOCKET_EVENT_CLOSED ||
               event_id == WEBSOCKET_EVENT_ERROR) {
        if (online) ESP_LOGW(TAG, "local Jarvis connection OFFLINE; reconnecting");
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
        .buffer_size = MAX_RX_BYTES,
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
