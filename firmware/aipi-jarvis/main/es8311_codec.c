#include "es8311_codec.h"

#include "aipi_board.h"
#include "driver/i2c_master.h"
#include "esp_check.h"
#include "esp_log.h"

#define ES8311_ADDRESS 0x18
#define ES8311_I2C_HZ 100000
#define ES8311_TIMEOUT_MS 100

static const char *TAG = "jarvis_es8311";
static i2c_master_bus_handle_t codec_bus;
static i2c_master_dev_handle_t codec_device;
static bool output_initialized;
static bool input_initialized;

esp_err_t es8311_codec_bus_initialize(void) {
    if (codec_bus && codec_device) return ESP_OK;
    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = AIPI_AUDIO_I2C_SDA,
        .scl_io_num = AIPI_AUDIO_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t result = i2c_new_master_bus(&bus_config, &codec_bus);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "shared codec bus init failed: %s", esp_err_to_name(result));
        return result;
    }
    i2c_device_config_t device_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = ES8311_ADDRESS,
        .scl_speed_hz = ES8311_I2C_HZ,
    };
    result = i2c_master_bus_add_device(codec_bus, &device_config, &codec_device);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "codec device registration failed: %s", esp_err_to_name(result));
        i2c_del_master_bus(codec_bus);
        codec_bus = NULL;
        return result;
    }
    ESP_LOGI(TAG, "shared new-I2C codec bus ready address=0x18 speed=100000");
    return ESP_OK;
}

bool es8311_codec_probe(void) {
    if (es8311_codec_bus_initialize() != ESP_OK) return false;
    esp_err_t result = i2c_master_probe(codec_bus, ES8311_ADDRESS, ES8311_TIMEOUT_MS);
    ESP_LOGI(TAG, "ES8311 new-I2C probe: %s", result == ESP_OK ? "PASS" : "FAIL");
    return result == ESP_OK;
}

esp_err_t es8311_codec_write_register(uint8_t reg, uint8_t value) {
    ESP_RETURN_ON_FALSE(codec_device, ESP_ERR_INVALID_STATE, TAG, "codec unavailable");
    uint8_t payload[2] = {reg, value};
    esp_err_t result = i2c_master_transmit(codec_device, payload, sizeof(payload),
                                           ES8311_TIMEOUT_MS);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "register write failed reg=0x%02x error=%s", reg,
                 esp_err_to_name(result));
    }
    return result;
}

esp_err_t es8311_codec_read_register(uint8_t reg, uint8_t *value) {
    ESP_RETURN_ON_FALSE(codec_device && value, ESP_ERR_INVALID_ARG, TAG,
                        "invalid register read");
    esp_err_t result = i2c_master_transmit_receive(codec_device, &reg, 1, value, 1,
                                                   ES8311_TIMEOUT_MS);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "register read failed reg=0x%02x error=%s", reg,
                 esp_err_to_name(result));
    }
    return result;
}

static esp_err_t configure_4096khz_mclk_16khz_pcm16(void) {
    uint8_t value = 0;
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x01, 0x3F), TAG, "clock source");
    ESP_RETURN_ON_ERROR(es8311_codec_read_register(0x02, &value), TAG, "clock reg02");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x02, value & 0x07), TAG, "clock reg02");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x03, 0x10), TAG, "ADC OSR");
    /* Espressif coeff_div entry {4096000, 16000}: ADC OSR=0x10,
       DAC OSR=0x20. The 0x10 DAC value belongs to the 24 kHz profile. */
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x04, 0x20), TAG, "DAC OSR");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x05, 0x00), TAG, "ADC DAC divider");
    ESP_RETURN_ON_ERROR(es8311_codec_read_register(0x06, &value), TAG, "BCLK read");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x06, (value & 0xE0) | 0x03),
                        TAG, "BCLK divider");
    ESP_RETURN_ON_ERROR(es8311_codec_read_register(0x07, &value), TAG, "LRCK read");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x07, value & 0xC0), TAG, "LRCK high");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x08, 0xFF), TAG, "LRCK low");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x09, 0x0C), TAG, "PCM16 I2S input");
    return ESP_OK;
}

esp_err_t es8311_codec_initialize_output(void) {
    if (output_initialized) return ESP_OK;
    ESP_RETURN_ON_ERROR(es8311_codec_bus_initialize(), TAG, "codec bus");
    uint8_t identity_register = 0;
    ESP_RETURN_ON_ERROR(es8311_codec_read_register(0x00, &identity_register), TAG,
                        "codec register access");

    /* Narrow speaker-only sequence cross-checked against Espressif esp_codec_dev
       and ESPHome ES8311. ADC/microphone capture remains disabled. */
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x44, 0x08), TAG, "I2C immunity 1");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x44, 0x08), TAG, "I2C immunity 2");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x00, 0x1F), TAG, "codec reset assert");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x00, 0x00), TAG, "codec reset release");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x0B, 0x00), TAG, "system 0B");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x0C, 0x00), TAG, "system 0C");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x10, 0x1F), TAG, "system 10");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x11, 0x7F), TAG, "system 11");
    ESP_RETURN_ON_ERROR(configure_4096khz_mclk_16khz_pcm16(), TAG, "clock setup");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x0D, 0x01), TAG, "analog power");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x0E, 0x02), TAG, "analog PGA");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x12, 0x00), TAG, "DAC power");
    /* AiPi Lite's onboard amplifier is fed from SPKOUT. Espressif's default
       0x10 enables HPOUT only, so enable both HP and speaker output drivers. */
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x13, 0x18), TAG,
                        "speaker and headphone output drivers");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x37, 0x08), TAG, "DAC EQ bypass");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x00, 0x80), TAG, "codec power on");
    ESP_RETURN_ON_ERROR(es8311_codec_set_volume(60), TAG, "bounded test volume");
    ESP_RETURN_ON_ERROR(es8311_codec_set_muted(true), TAG, "initial mute");
    output_initialized = true;
    ESP_LOGI(TAG, "ES8311 speaker-only init PASS MCLK=4096000 rate=16000 PCM16");
    return ESP_OK;
}

esp_err_t es8311_codec_set_volume(unsigned volume) {
    ESP_RETURN_ON_FALSE(volume <= 60, ESP_ERR_INVALID_ARG, TAG, "unsafe volume");
    uint8_t register_value = (uint8_t)((volume * 255U) / 100U);
    return es8311_codec_write_register(0x32, register_value);
}

esp_err_t es8311_codec_set_muted(bool muted) {
    uint8_t value = 0;
    ESP_RETURN_ON_ERROR(es8311_codec_read_register(0x31, &value), TAG, "mute read");
    value &= 0x9F;
    if (muted) value |= 0x60;
    return es8311_codec_write_register(0x31, value);
}

esp_err_t es8311_codec_shutdown(void) {
    if (!codec_device) return ESP_OK;
    esp_err_t result = es8311_codec_set_muted(true);
    output_initialized = false;
    return result;
}

/* Microphone input.
 *
 * Kept strictly additive to the physically validated speaker configuration:
 * this writes only ADC registers and never re-touches the DAC, output routing
 * (0x13), or the clock dividers that the speaker PASS depends on. Register
 * values follow Espressif's esp_codec_dev ES8311 reference for an analog
 * single-ended microphone.
 *
 * Input is initialized only when capture is actually requested, so a build
 * that never listens leaves the ADC powered down. */
esp_err_t es8311_codec_initialize_input(void) {
    if (input_initialized) return ESP_OK;
    ESP_RETURN_ON_FALSE(output_initialized, ESP_ERR_INVALID_STATE, TAG,
                        "codec output must be initialized first");
    /* 0x1A: ADC digital volume ramp; 0x1B/0x1C: ADC high-pass and equalizer
     * defaults that remove DC offset from the electret input. */
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x15, 0x40), TAG, "ADC ramp");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x1B, 0x0A), TAG, "ADC HPF 1");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x1C, 0x6A), TAG, "ADC HPF 2");
    /* 0x14: analog microphone, single-ended, with PGA gain. The digital
     * microphone bit stays clear; this board has an analog electret. */
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x14, 0x1A), TAG, "mic select");
    /* 0x17: ADC digital volume. Conservative: enough level for speech without
     * clipping close talkers at the door. */
    /* 0x16: ADC PGA gain scale. Espressif's reference sets this and the first
     * implementation omitted it, which left the analog front end near unity and
     * captured close to the noise floor. 0x05 is the reference's 30 dB step. */
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x16, 0x05), TAG, "ADC gain");
    ESP_RETURN_ON_ERROR(es8311_codec_write_register(0x17, 0xBF), TAG, "ADC volume");
    input_initialized = true;

    /* Read the ADC registers back rather than trusting the writes. A silent or
     * quiet microphone is otherwise indistinguishable from a register that did
     * not take. */
    static const uint8_t audit[] = {0x14, 0x15, 0x16, 0x17, 0x1B, 0x1C};
    for (size_t i = 0; i < sizeof(audit) / sizeof(audit[0]); ++i) {
        uint8_t value = 0;
        if (es8311_codec_read_register(audit[i], &value) == ESP_OK) {
            ESP_LOGI(TAG, "ADC register 0x%02X = 0x%02X", audit[i], value);
        }
    }
    ESP_LOGI(TAG, "ES8311 microphone input PASS rate=16000 PCM16 analog-mic");
    return ESP_OK;
}

esp_err_t es8311_codec_set_input_muted(bool muted) {
    if (!input_initialized) return ESP_ERR_INVALID_STATE;
    /* 0x17 is the ADC digital volume; zero is a hard digital mute, which is
     * stronger than relying on the caller to stop reading. */
    return es8311_codec_write_register(0x17, muted ? 0x00 : 0xBF);
}

bool es8311_codec_input_ready(void) {
    return input_initialized;
}
