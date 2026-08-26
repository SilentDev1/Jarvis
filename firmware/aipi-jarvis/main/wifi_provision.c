#include "wifi_provision.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aipi_board.h"
#include "bringup.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs.h"

#define WIFI_NAMESPACE "jarvis_wifi"
#define WIFI_KEY_SSID "ssid"
#define WIFI_KEY_PASSWORD "password"
#define WIFI_KEY_RECONNECT_TEST "reconnect_ok"
#define WIFI_KEY_JARVIS_HOST "jarvis_host"
#define WIFI_KEY_JARVIS_PORT "jarvis_port"
#define WIFI_KEY_DEVICE_PASSWORD "device_password"
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAILED_BIT BIT1
#define WIFI_CONNECT_RETRIES 5

static const char *TAG = "jarvis_wifi";
static EventGroupHandle_t events;
static httpd_handle_t portal;
static wifi_provision_status_t status;
static bool reconnect_task_running;
static bool reconnect_selftest_complete;
static bool reconnect_selftest_started;
static bool reconnect_selftest_disconnect_seen;

static const char PORTAL_HTML[] =
    "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<link rel=icon href='data:,'>"
    "<title>Jarvis AiPi Setup</title><style>body{font:18px system-ui;max-width:30em;"
    "margin:3em auto;padding:1em}input,button{box-sizing:border-box;width:100%;padding:.8em;"
    "margin:.4em 0}</style><h1>Jarvis AiPi Wi-Fi</h1><form method=post action=/provision>"
    "<label>Network name<input name=ssid maxlength=32 required autocomplete=off></label>"
    "<label>Wi-Fi password<input name=password type=password minlength=8 maxlength=63 required>"
    "</label><h2>Local Jarvis</h2>"
    "<label>Jarvis host<input name=host maxlength=80 required value=jarvis.local "
    "autocomplete=off></label><label>Gateway port<input name=port type=number min=1 "
    "max=65535 required value=8767></label>"
    "<label>Device password<input name=device_password type=password minlength=12 maxlength=64 "
    "required autocomplete=new-password autocapitalize=none spellcheck=false></label>"
    "<button>Connect</button></form>";

static bool load_credentials(char ssid[33], char password[64]) {
    nvs_handle_t handle;
    if (nvs_open(WIFI_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    size_t ssid_len = 33, password_len = 64;
    esp_err_t a = nvs_get_str(handle, WIFI_KEY_SSID, ssid, &ssid_len);
    esp_err_t b = nvs_get_str(handle, WIFI_KEY_PASSWORD, password, &password_len);
    nvs_close(handle);
    return a == ESP_OK && b == ESP_OK && ssid_len > 1 && password_len >= 9;
}

static esp_err_t save_credentials(const char *ssid, const char *password) {
    nvs_handle_t handle;
    esp_err_t result = nvs_open(WIFI_NAMESPACE, NVS_READWRITE, &handle);
    if (result != ESP_OK) return result;
    if ((result = nvs_set_str(handle, WIFI_KEY_SSID, ssid)) == ESP_OK &&
        (result = nvs_set_str(handle, WIFI_KEY_PASSWORD, password)) == ESP_OK) {
        result = nvs_commit(handle);
    }
    nvs_close(handle);
    return result;
}

bool wifi_provision_load_jarvis_config(jarvis_local_config_t *config) {
    if (!config) return false;
    memset(config, 0, sizeof(*config));
    nvs_handle_t handle;
    if (nvs_open(WIFI_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    size_t host_len = sizeof(config->host), password_len = sizeof(config->device_password);
    esp_err_t a = nvs_get_str(handle, WIFI_KEY_JARVIS_HOST, config->host, &host_len);
    esp_err_t b = nvs_get_u16(handle, WIFI_KEY_JARVIS_PORT, &config->port);
    esp_err_t c = nvs_get_str(handle, WIFI_KEY_DEVICE_PASSWORD, config->device_password,
                              &password_len);
    nvs_close(handle);
    return a == ESP_OK && b == ESP_OK && c == ESP_OK && host_len > 1 &&
           config->port > 0 && password_len >= 13;
}

static esp_err_t save_jarvis_config(const char *host, uint16_t port,
                                    const char *device_password) {
    nvs_handle_t handle;
    esp_err_t result = nvs_open(WIFI_NAMESPACE, NVS_READWRITE, &handle);
    if (result != ESP_OK) return result;
    if ((result = nvs_set_str(handle, WIFI_KEY_JARVIS_HOST, host)) == ESP_OK &&
        (result = nvs_set_u16(handle, WIFI_KEY_JARVIS_PORT, port)) == ESP_OK &&
        (result = nvs_set_str(handle, WIFI_KEY_DEVICE_PASSWORD, device_password)) == ESP_OK) {
        result = nvs_commit(handle);
    }
    nvs_close(handle);
    return result;
}

static bool load_reconnect_test(void) {
    nvs_handle_t handle;
    uint8_t value = 0;
    if (nvs_open(WIFI_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_get_u8(handle, WIFI_KEY_RECONNECT_TEST, &value);
    nvs_close(handle);
    return result == ESP_OK && value == 1;
}

static void save_reconnect_test(void) {
    nvs_handle_t handle;
    if (nvs_open(WIFI_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return;
    if (nvs_set_u8(handle, WIFI_KEY_RECONNECT_TEST, 1) == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
}

esp_err_t wifi_provision_clear_custom_config(void) {
    nvs_handle_t handle;
    esp_err_t result = nvs_open(WIFI_NAMESPACE, NVS_READWRITE, &handle);
    if (result != ESP_OK) return result;
    result = nvs_erase_all(handle);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "custom Wi-Fi configuration cleared");
    return result;
}

bool wifi_provision_boot_reset_requested(void) {
    if (gpio_get_level(AIPI_BUTTON) != 0) return false;
    ESP_LOGW(TAG, "button held at boot; hold for 8 seconds to clear custom Wi-Fi only");
    for (int elapsed = 0; elapsed < AIPI_WIFI_RESET_HOLD_MS; elapsed += 100) {
        if (gpio_get_level(AIPI_BUTTON) != 0) return false;
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    return true;
}

static void reconnect_task(void *unused) {
    (void)unused;
    int delay_seconds = 1;
    while (!status.connected && status.configured) {
        vTaskDelay(pdMS_TO_TICKS(delay_seconds * 1000));
        status.retry_count++;
        ESP_LOGI(TAG, "reconnect attempt=%d", status.retry_count);
        esp_wifi_connect();
        if (delay_seconds < 30) delay_seconds *= 2;
        if (delay_seconds > 30) delay_seconds = 30;
    }
    reconnect_task_running = false;
    vTaskDelete(NULL);
}

static void reconnect_selftest_task(void *unused) {
    (void)unused;
    vTaskDelay(pdMS_TO_TICKS(3000));
    ESP_LOGI(TAG, "one-time reconnect self-test: controlled disconnect");
    esp_wifi_disconnect();
    vTaskDelete(NULL);
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        status.connected = false;
        status.ip[0] = '\0';
        xEventGroupSetBits(events, WIFI_FAILED_BIT);
        if (reconnect_selftest_started && !reconnect_selftest_complete) {
            reconnect_selftest_disconnect_seen = true;
        }
        if (status.configured && status.retry_count == 0 && !reconnect_task_running) {
            reconnect_task_running = true;
            xTaskCreate(reconnect_task, "wifi_reconnect", 3072, NULL, 4, NULL);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *got_ip = data;
        snprintf(status.ip, sizeof(status.ip), IPSTR, IP2STR(&got_ip->ip_info.ip));
        status.connected = true;
        status.retry_count = 0;
        xEventGroupClearBits(events, WIFI_FAILED_BIT);
        xEventGroupSetBits(events, WIFI_CONNECTED_BIT);
        ESP_LOGI(TAG, "connected via DHCP ip=%s", status.ip);
        bringup_display_status4("JARVIS", "WI-FI: CONNECTED", status.ip, "JARVIS: NEXT");
        if (!reconnect_selftest_complete && !reconnect_selftest_started) {
            reconnect_selftest_started = true;
            BaseType_t created = xTaskCreate(reconnect_selftest_task, "wifi_selftest", 3072,
                                             NULL, 4, NULL);
            ESP_LOGI(TAG, "one-time reconnect self-test scheduled=%s",
                     created == pdPASS ? "YES" : "NO");
        } else if (!reconnect_selftest_complete && reconnect_selftest_disconnect_seen) {
            reconnect_selftest_complete = true;
            save_reconnect_test();
            ESP_LOGI(TAG, "one-time reconnect self-test: PASS");
        }
    }
}

static esp_err_t portal_get(httpd_req_t *request) {
    httpd_resp_set_type(request, "text/html");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_send(request, PORTAL_HTML, HTTPD_RESP_USE_STRLEN);
}

static int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    c = (char)tolower((unsigned char)c);
    return c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
}

static bool url_decode_field(const char *body, const char *name, char *output, size_t capacity) {
    size_t name_len = strlen(name);
    const char *cursor = body;
    while (cursor && *cursor) {
        if ((cursor == body || cursor[-1] == '&') && strncmp(cursor, name, name_len) == 0 &&
            cursor[name_len] == '=') {
            cursor += name_len + 1;
            size_t used = 0;
            while (*cursor && *cursor != '&') {
                unsigned char value;
                if (*cursor == '+') { value = ' '; cursor++; }
                else if (*cursor == '%' && cursor[1] && cursor[2]) {
                    int high = hex_value(cursor[1]), low = hex_value(cursor[2]);
                    if (high < 0 || low < 0) return false;
                    value = (unsigned char)((high << 4) | low); cursor += 3;
                } else { value = (unsigned char)*cursor++; }
                if (value == 0 || used + 1 >= capacity) return false;
                output[used++] = (char)value;
            }
            output[used] = '\0';
            return used > 0;
        }
        cursor = strchr(cursor, '&');
        if (cursor) cursor++;
    }
    return false;
}

static void restart_task(void *unused) {
    (void)unused;
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_restart();
}

static esp_err_t portal_post(httpd_req_t *request) {
    if (request->content_len <= 0 || request->content_len > 512) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid request");
    }
    char body[513] = {0};
    int received = 0;
    while (received < request->content_len) {
        int count = httpd_req_recv(request, body + received, request->content_len - received);
        if (count <= 0) return ESP_FAIL;
        received += count;
    }
    char ssid[33] = {0}, password[64] = {0}, host[81] = {0},
         device_password[65] = {0};
    char port_text[6] = {0};
    bool valid = url_decode_field(body, "ssid", ssid, sizeof(ssid)) &&
                 url_decode_field(body, "password", password, sizeof(password)) &&
                 url_decode_field(body, "host", host, sizeof(host)) &&
                 url_decode_field(body, "port", port_text, sizeof(port_text)) &&
                 url_decode_field(body, "device_password", device_password,
                                  sizeof(device_password));
    size_t ssid_len = strlen(ssid), password_len = strlen(password), host_len = strlen(host),
           device_password_len = strlen(device_password);
    char *port_end = NULL;
    long port = strtol(port_text, &port_end, 10);
    if (!valid || ssid_len < 1 || ssid_len > 32 || password_len < 8 || password_len > 63 ||
        host_len < 1 || host_len > 80 || device_password_len < 12 ||
        device_password_len > 64 ||
        !port_end || *port_end != '\0' || port < 1 || port > 65535) {
        memset(password, 0, sizeof(password));
        memset(device_password, 0, sizeof(device_password));
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid setup fields");
    }
    esp_err_t result = save_credentials(ssid, password);
    if (result == ESP_OK) {
        result = save_jarvis_config(host, (uint16_t)port, device_password);
    }
    memset(password, 0, sizeof(password));
    memset(device_password, 0, sizeof(device_password));
    memset(body, 0, sizeof(body));
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "credential storage failed: %s", esp_err_to_name(result));
        return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Storage failed");
    }
    ESP_LOGI(TAG, "Wi-Fi and local Jarvis configuration saved (secrets omitted)");
    status.configured = true;
    bringup_display_status("JARVIS", "WI-FI SAVED", "RESTARTING");
    httpd_resp_set_type(request, "text/html");
    httpd_resp_sendstr(request, "<h1>Saved</h1><p>Jarvis AiPi is restarting.</p>");
    xTaskCreate(restart_task, "wifi_restart", 2048, NULL, 5, NULL);
    return ESP_OK;
}

static void random_setup_password(char output[13]) {
    static const char alphabet[] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    uint32_t random = 0;
    for (int i = 0; i < 12; ++i) {
        if ((i % 4) == 0) random = esp_random();
        output[i] = alphabet[(random >> ((i % 4) * 8)) % (sizeof(alphabet) - 1)];
    }
    output[12] = '\0';
}

static esp_err_t start_setup_ap(void) {
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP));
    char ap_ssid[33], ap_password[13];
    snprintf(ap_ssid, sizeof(ap_ssid), "Jarvis-AiPi-%02X%02X", mac[4], mac[5]);
    random_setup_password(ap_password);
    wifi_config_t config = {0};
    strlcpy((char *)config.ap.ssid, ap_ssid, sizeof(config.ap.ssid));
    strlcpy((char *)config.ap.password, ap_password, sizeof(config.ap.password));
    config.ap.ssid_len = strlen(ap_ssid);
    config.ap.max_connection = 1;
    config.ap.authmode = WIFI_AUTH_WPA2_PSK;
    esp_netif_create_default_wifi_ap();
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
    httpd_config_t server_config = HTTPD_DEFAULT_CONFIG();
    server_config.max_open_sockets = 2;
    server_config.lru_purge_enable = true;
    ESP_ERROR_CHECK(httpd_start(&portal, &server_config));
    httpd_uri_t get = {.uri = "/", .method = HTTP_GET, .handler = portal_get};
    httpd_uri_t post = {.uri = "/provision", .method = HTTP_POST, .handler = portal_post};
    ESP_ERROR_CHECK(httpd_register_uri_handler(portal, &get));
    ESP_ERROR_CHECK(httpd_register_uri_handler(portal, &post));
    bringup_display_status4("JARVIS", "SETUP 192.168.4.1", ap_ssid, ap_password);
    ESP_LOGI(TAG, "setup AP active ssid=%s password=DISPLAY_ONLY clients=1", ap_ssid);
    return ESP_OK;
}

esp_err_t wifi_provision_start(void) {
    events = xEventGroupCreate();
    if (!events) return ESP_ERR_NO_MEM;
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_log_level_set("wifi", ESP_LOG_WARN);
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    char ssid[33] = {0}, password[64] = {0};
    status.configured = load_credentials(ssid, password);
    if (!status.configured) return start_setup_ap();
    reconnect_selftest_complete = load_reconnect_test();
    ESP_LOGI(TAG, "one-time reconnect self-test previously_passed=%s",
             reconnect_selftest_complete ? "YES" : "NO");
    esp_netif_create_default_wifi_sta();
    wifi_config_t config = {0};
    strlcpy((char *)config.sta.ssid, ssid, sizeof(config.sta.ssid));
    strlcpy((char *)config.sta.password, password, sizeof(config.sta.password));
    memset(password, 0, sizeof(password));
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
    bringup_display_status("JARVIS", "WI-FI", "CONNECTING");
    for (int attempt = 1; attempt <= WIFI_CONNECT_RETRIES; ++attempt) {
        status.retry_count = attempt;
        xEventGroupClearBits(events, WIFI_CONNECTED_BIT | WIFI_FAILED_BIT);
        ESP_LOGI(TAG, "connect attempt=%d", attempt);
        ESP_ERROR_CHECK(esp_wifi_connect());
        EventBits_t bits = xEventGroupWaitBits(events, WIFI_CONNECTED_BIT, pdFALSE, pdFALSE,
                                                pdMS_TO_TICKS(10000));
        if (bits & WIFI_CONNECTED_BIT) return ESP_OK;
        vTaskDelay(pdMS_TO_TICKS(attempt * 1000));
    }
    ESP_LOGW(TAG, "bounded connection attempts exhausted; entering setup without deleting config");
    ESP_ERROR_CHECK(esp_wifi_stop());
    return start_setup_ap();
}

wifi_provision_status_t wifi_provision_status(void) { return status; }

#define GATEWAY_IP_KEY "gw_ip"

bool wifi_provision_cached_gateway_ip(char *out, size_t size) {
    nvs_handle_t handle;
    if (nvs_open(WIFI_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    size_t length = size;
    esp_err_t result = nvs_get_str(handle, GATEWAY_IP_KEY, out, &length);
    nvs_close(handle);
    return result == ESP_OK && out[0] != '\0';
}

void wifi_provision_store_gateway_ip(const char *ip) {
    if (!ip || !ip[0]) return;
    char existing[48] = {0};
    /* Only write when the address actually changed; NVS has finite erase
     * cycles and this runs on every successful connection. */
    if (wifi_provision_cached_gateway_ip(existing, sizeof(existing)) &&
        strcmp(existing, ip) == 0) {
        return;
    }
    nvs_handle_t handle;
    if (nvs_open(WIFI_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return;
    if (nvs_set_str(handle, GATEWAY_IP_KEY, ip) == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
}
