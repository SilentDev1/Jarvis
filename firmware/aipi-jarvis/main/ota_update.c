#include "ota_update.h"

#include <stdio.h>
#include <string.h>

#include "audio_output.h"
#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/md.h"
#include "mbedtls/pk.h"
#include "mbedtls/sha256.h"
#include "wifi_provision.h"

#define TAG "jarvis_ota"

/* Bounds. The image must fit the slot with room to spare, and a manifest field
 * that does not fit these buffers is malformed by definition. */
#define OTA_MAX_IMAGE_BYTES 3500000
#define OTA_MIN_IMAGE_BYTES 100000
#define OTA_HTTP_BUFFER 4096
#define OTA_VERSION_MAX 48
#define OTA_BUILD_ID_MAX 72
#define OTA_URL_MAX 160
#define OTA_SIGNATURE_MAX 1024
#define OTA_CANONICAL_MAX 1400
#define OTA_HARDWARE_ID "aipi-lite-esp32s3"
#define OTA_DEVICE_ID "aipi-front-door"

extern const uint8_t ota_public_key_pem_start[] asm("_binary_ota_public_key_pem_start");
extern const uint8_t ota_public_key_pem_end[] asm("_binary_ota_public_key_pem_end");

typedef struct {
    char version[OTA_VERSION_MAX];
    char build_id[OTA_BUILD_ID_MAX];
    char sha256[65];
    char channel[24];
    char url[OTA_URL_MAX];
    char signature[OTA_SIGNATURE_MAX];
    int size;
    int minimum_bootloader;
} ota_offer_t;

static volatile bool ota_in_flight;
static ota_offer_t pending_offer;
static ota_progress_fn progress_cb;

bool ota_update_active(void) { return ota_in_flight; }

static void report(const char *state, int percent, const char *detail) {
    if (progress_cb) progress_cb(state, percent, detail);
}

const char *ota_update_running_slot(void) {
    const esp_partition_t *running = esp_ota_get_running_partition();
    return running ? running->label : "unknown";
}

bool ota_update_pending_verify(void) {
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (!running || esp_ota_get_state_partition(running, &state) != ESP_OK) return false;
    return state == ESP_OTA_IMG_PENDING_VERIFY;
}

esp_err_t ota_update_mark_valid(void) {
    if (!ota_update_pending_verify()) return ESP_OK;
    esp_err_t result = esp_ota_mark_app_valid_cancel_rollback();
    ESP_LOGI(TAG, "running image marked valid: %s", esp_err_to_name(result));
    return result;
}

/* Rebuilds the exact bytes the publisher signed.
 *
 * The host signs a canonical JSON encoding: keys sorted, no whitespace. It is
 * rebuilt here field by field rather than re-serialising the received JSON,
 * because any difference in key order or spacing would fail verification even
 * for a legitimate update. */
static int build_canonical(const ota_offer_t *offer, char *out, size_t max) {
    return snprintf(out, max,
        "{\"buildId\":\"%.*s\",\"channel\":\"%.*s\",\"deviceId\":\"%s\","
        "\"hardware\":\"%s\",\"minimumBootloaderVersion\":%d,"
        "\"sha256\":\"%.*s\",\"size\":%d,\"version\":\"%.*s\"}",
        (int)(OTA_BUILD_ID_MAX - 1), offer->build_id,
        (int)(sizeof(offer->channel) - 1), offer->channel,
        OTA_DEVICE_ID, OTA_HARDWARE_ID, offer->minimum_bootloader,
        64, offer->sha256, offer->size,
        (int)(OTA_VERSION_MAX - 1), offer->version);
}

static int hex_to_bytes(const char *hex, uint8_t *out, size_t max) {
    size_t length = strlen(hex);
    if (length % 2 || length / 2 > max) return -1;
    for (size_t i = 0; i < length / 2; ++i) {
        unsigned value;
        if (sscanf(hex + i * 2, "%2x", &value) != 1) return -1;
        out[i] = (uint8_t)value;
    }
    return (int)(length / 2);
}

/* Verifies the manifest signature against the embedded public key.
 *
 * This is the check that makes a compromised gateway insufficient to install
 * firmware: the signing key never leaves the owner's machine. */
static bool signature_valid(const ota_offer_t *offer) {
    static char canonical[OTA_CANONICAL_MAX];
    int written = build_canonical(offer, canonical, sizeof(canonical));
    if (written <= 0 || written >= (int)sizeof(canonical)) {
        ESP_LOGE(TAG, "manifest too large to canonicalise");
        return false;
    }

    static uint8_t signature[OTA_SIGNATURE_MAX / 2];
    int signature_len = hex_to_bytes(offer->signature, signature, sizeof(signature));
    if (signature_len <= 0) {
        ESP_LOGE(TAG, "malformed signature encoding");
        return false;
    }

    uint8_t digest[32];
    mbedtls_sha256((const unsigned char *)canonical, (size_t)written, digest, 0);

    mbedtls_pk_context key;
    mbedtls_pk_init(&key);
    size_t key_len = ota_public_key_pem_end - ota_public_key_pem_start;
    int rc = mbedtls_pk_parse_public_key(&key, ota_public_key_pem_start, key_len);
    if (rc != 0) {
        ESP_LOGE(TAG, "embedded public key unusable: -0x%04x", -rc);
        mbedtls_pk_free(&key);
        return false;
    }
    rc = mbedtls_pk_verify(&key, MBEDTLS_MD_SHA256, digest, sizeof(digest),
                           signature, (size_t)signature_len);
    mbedtls_pk_free(&key);
    if (rc != 0) {
        ESP_LOGE(TAG, "manifest signature INVALID: -0x%04x", -rc);
        return false;
    }
    ESP_LOGI(TAG, "manifest signature verified");
    return true;
}

static void ota_task(void *unused) {
    (void)unused;
    const ota_offer_t *offer = &pending_offer;
    /* Signature verification happens here rather than in the websocket event
     * handler: mbedtls RSA needs several KB of stack, and doing it on the
     * websocket task overflowed it and rebooted the device. */
    if (!signature_valid(offer)) {
        ESP_LOGE(TAG, "OTA refused: manifest signature invalid");
        report("FAILED", 0, "bad_signature");
        ota_in_flight = false;
        vTaskDelete(NULL);
        return;
    }
    esp_err_t result = ESP_FAIL;
    esp_ota_handle_t handle = 0;
    const esp_partition_t *target = NULL;
    esp_http_client_handle_t client = NULL;
    char *buffer = NULL;
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    const char *failure = "unknown";

    target = esp_ota_get_next_update_partition(NULL);
    if (!target) { failure = "no_inactive_slot"; goto done; }
    if (offer->size > (int)target->size) { failure = "image_exceeds_slot"; goto done; }
    ESP_LOGI(TAG, "OTA target slot=%s size=%d bytes", target->label, offer->size);

    /* Reuse the provisioned gateway and device credential: firmware is fetched
     * from the same authenticated Jarvis the device already trusts, over the
     * LAN. No public Internet, no third-party host. */
    jarvis_local_config_t provisioned;
    if (!wifi_provision_load_jarvis_config(&provisioned)) {
        failure = "gateway_unknown"; goto done;
    }
    char url[OTA_URL_MAX + 128];
    snprintf(url, sizeof(url), "http://%.*s:%u%.*s",
             (int)(sizeof(provisioned.host) - 1), provisioned.host,
             provisioned.port,
             (int)(OTA_URL_MAX - 1), offer->url);
    char credential[96];
    snprintf(credential, sizeof(credential), "DevicePassword %.*s",
             (int)(sizeof(provisioned.device_password) - 1),
             provisioned.device_password);
    memset(provisioned.device_password, 0, sizeof(provisioned.device_password));

    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = 20000,
        .keep_alive_enable = true,
    };
    client = esp_http_client_init(&config);
    if (!client) { failure = "http_init"; goto done; }
    esp_http_client_set_header(client, "Authorization", credential);
    /* Wipe the credential from the stack as soon as the header is set. */
    memset(credential, 0, sizeof(credential));

    if (esp_http_client_open(client, 0) != ESP_OK) { failure = "connect_failed"; goto done; }
    int content_length = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        ESP_LOGE(TAG, "firmware download rejected: HTTP %d", status);
        failure = "http_status"; goto done;
    }
    if (content_length > 0 && content_length != offer->size) {
        failure = "size_mismatch"; goto done;
    }

    buffer = malloc(OTA_HTTP_BUFFER);
    if (!buffer) { failure = "no_memory"; goto done; }

    /* esp_ota_begin erases the inactive slot only. The running image is never
     * touched, so losing power here leaves the device bootable. */
    result = esp_ota_begin(target, offer->size, &handle);
    if (result != ESP_OK) { failure = "ota_begin"; goto done; }

    mbedtls_sha256_starts(&sha, 0);
    int received = 0, last_percent = -1;
    while (received < offer->size) {
        int read = esp_http_client_read(client, buffer, OTA_HTTP_BUFFER);
        if (read < 0) { failure = "read_error"; goto done; }
        if (read == 0) break;
        if (received + read > offer->size) { failure = "oversized_stream"; goto done; }
        mbedtls_sha256_update(&sha, (const unsigned char *)buffer, (size_t)read);
        result = esp_ota_write(handle, buffer, (size_t)read);
        if (result != ESP_OK) { failure = "flash_write"; goto done; }
        received += read;
        int percent = (int)((int64_t)received * 100 / offer->size);
        if (percent != last_percent && percent % 5 == 0) {
            last_percent = percent;
            report("DOWNLOADING", percent, NULL);
        }
    }
    if (received != offer->size) { failure = "truncated_download"; goto done; }

    report("VERIFYING", 100, NULL);
    uint8_t digest[32];
    mbedtls_sha256_finish(&sha, digest);
    char actual[65];
    for (int i = 0; i < 32; ++i) snprintf(actual + i * 2, 3, "%02x", digest[i]);
    if (strcmp(actual, offer->sha256) != 0) {
        /* The image is not what was signed. Abort rather than boot it. */
        ESP_LOGE(TAG, "SHA-256 mismatch; refusing image");
        failure = "sha256_mismatch"; goto done;
    }

    result = esp_ota_end(handle);
    handle = 0;
    if (result != ESP_OK) { failure = "image_invalid"; goto done; }

    result = esp_ota_set_boot_partition(target);
    if (result != ESP_OK) { failure = "set_boot"; goto done; }

    ESP_LOGI(TAG, "OTA staged to %s; rebooting into it", target->label);
    report("REBOOTING", 100, NULL);
    esp_http_client_cleanup(client);
    client = NULL;
    free(buffer);
    mbedtls_sha256_free(&sha);
    ota_in_flight = false;
    vTaskDelay(pdMS_TO_TICKS(1200));
    esp_restart();

done:
    if (handle) esp_ota_abort(handle);
    if (client) esp_http_client_cleanup(client);
    free(buffer);
    mbedtls_sha256_free(&sha);
    ESP_LOGE(TAG, "OTA failed: %s", failure);
    report("FAILED", 0, failure);
    ota_in_flight = false;
    vTaskDelete(NULL);
}

esp_err_t ota_update_handle_offer(const cJSON *root, ota_progress_fn reporter) {
    if (ota_in_flight) return ESP_ERR_INVALID_STATE;
    /* Never update while the speaker or microphone is live. The host checks
     * this too; both must agree before firmware is replaced. */
    if (audio_playback_active() || audio_input_active()) return ESP_ERR_INVALID_STATE;

    const cJSON *manifest = cJSON_GetObjectItemCaseSensitive(root, "manifest");
    const cJSON *signature = cJSON_GetObjectItemCaseSensitive(root, "signature");
    const cJSON *url = cJSON_GetObjectItemCaseSensitive(root, "url");
    if (!cJSON_IsObject(manifest) || !cJSON_IsString(signature) || !cJSON_IsString(url)) {
        return ESP_ERR_INVALID_ARG;
    }

    const cJSON *version = cJSON_GetObjectItemCaseSensitive(manifest, "version");
    const cJSON *hardware = cJSON_GetObjectItemCaseSensitive(manifest, "hardware");
    const cJSON *device = cJSON_GetObjectItemCaseSensitive(manifest, "deviceId");
    const cJSON *sha = cJSON_GetObjectItemCaseSensitive(manifest, "sha256");
    const cJSON *size = cJSON_GetObjectItemCaseSensitive(manifest, "size");
    const cJSON *build = cJSON_GetObjectItemCaseSensitive(manifest, "buildId");
    const cJSON *channel = cJSON_GetObjectItemCaseSensitive(manifest, "channel");
    const cJSON *bootloader =
        cJSON_GetObjectItemCaseSensitive(manifest, "minimumBootloaderVersion");

    if (!cJSON_IsString(version) || !cJSON_IsString(hardware) ||
        !cJSON_IsString(sha) || !cJSON_IsNumber(size) || !cJSON_IsString(build) ||
        !cJSON_IsString(channel) || !cJSON_IsNumber(bootloader) ||
        !cJSON_IsString(device)) {
        ESP_LOGW(TAG, "OTA offer rejected: malformed manifest");
        return ESP_ERR_INVALID_ARG;
    }
    /* Refuse firmware built for anything but this board and this device. */
    if (strcmp(hardware->valuestring, OTA_HARDWARE_ID) != 0) {
        ESP_LOGW(TAG, "OTA offer rejected: wrong hardware");
        return ESP_ERR_INVALID_ARG;
    }
    if (strcmp(device->valuestring, OTA_DEVICE_ID) != 0) {
        ESP_LOGW(TAG, "OTA offer rejected: wrong device");
        return ESP_ERR_INVALID_ARG;
    }
    if (strlen(sha->valuestring) != 64) return ESP_ERR_INVALID_ARG;
    if (size->valueint < OTA_MIN_IMAGE_BYTES || size->valueint > OTA_MAX_IMAGE_BYTES) {
        ESP_LOGW(TAG, "OTA offer rejected: implausible image size %d", size->valueint);
        return ESP_ERR_INVALID_SIZE;
    }
    if (strlen(version->valuestring) >= OTA_VERSION_MAX ||
        strlen(build->valuestring) >= OTA_BUILD_ID_MAX ||
        strlen(url->valuestring) >= OTA_URL_MAX ||
        strlen(signature->valuestring) >= OTA_SIGNATURE_MAX) {
        return ESP_ERR_INVALID_SIZE;
    }

    memset(&pending_offer, 0, sizeof(pending_offer));
    snprintf(pending_offer.version, OTA_VERSION_MAX, "%s", version->valuestring);
    snprintf(pending_offer.build_id, OTA_BUILD_ID_MAX, "%s", build->valuestring);
    snprintf(pending_offer.sha256, sizeof(pending_offer.sha256), "%s", sha->valuestring);
    snprintf(pending_offer.channel, sizeof(pending_offer.channel), "%s", channel->valuestring);
    snprintf(pending_offer.url, OTA_URL_MAX, "%s", url->valuestring);
    snprintf(pending_offer.signature, OTA_SIGNATURE_MAX, "%s", signature->valuestring);
    pending_offer.size = size->valueint;
    pending_offer.minimum_bootloader = bootloader->valueint;

    progress_cb = reporter;
    ota_in_flight = true;
    report("DOWNLOADING", 0, NULL);
    /* Sized for mbedtls RSA verification plus the HTTP and flash write path. */
    if (xTaskCreate(ota_task, "aipi_ota", 12288, NULL, 4, NULL) != pdPASS) {
        ota_in_flight = false;
        report("FAILED", 0, "no_task_memory");
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
