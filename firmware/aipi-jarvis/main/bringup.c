#include "bringup.h"

#include <ctype.h>
#include <stdint.h>
#include <string.h>

#include "aipi_board.h"
#include "audio_output.h"
#include "local_connection.h"
#include "es8311_codec.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "display_render.h"
#include "display_controller.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "aipi_bringup";
static spi_device_handle_t lcd;

static esp_err_t lcd_tx(uint8_t command, const void *data, size_t length) {
    gpio_set_level(AIPI_LCD_DC, 0);
    spi_transaction_t cmd = {.length = 8, .tx_buffer = &command};
    ESP_RETURN_ON_ERROR(spi_device_polling_transmit(lcd, &cmd), TAG, "lcd command");
    if (length == 0) return ESP_OK;
    gpio_set_level(AIPI_LCD_DC, 1);
    spi_transaction_t payload = {.length = length * 8, .tx_buffer = data};
    return spi_device_polling_transmit(lcd, &payload);
}

static void lcd_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {
    uint8_t cols[] = {0, (uint8_t)(x0 + 2), 0, (uint8_t)(x1 + 2)};
    uint8_t rows[] = {0, (uint8_t)(y0 + 1), 0, (uint8_t)(y1 + 1)};
    ESP_ERROR_CHECK(lcd_tx(0x2a, cols, sizeof(cols)));
    ESP_ERROR_CHECK(lcd_tx(0x2b, rows, sizeof(rows)));
    ESP_ERROR_CHECK(lcd_tx(0x2c, NULL, 0));
}

static void lcd_fill(uint16_t color) {
    uint16_t pixels[128];
    for (size_t i = 0; i < 128; ++i) pixels[i] = __builtin_bswap16(color);
    lcd_window(0, 0, 127, 127);
    gpio_set_level(AIPI_LCD_DC, 1);
    for (size_t row = 0; row < 128; ++row) {
        spi_transaction_t tx = {.length = sizeof(pixels) * 8, .tx_buffer = pixels};
        ESP_ERROR_CHECK(spi_device_polling_transmit(lcd, &tx));
    }
}

static const uint8_t *glyph(char input) {
    static const uint8_t blank[7] = {0};
    static const struct { char c; uint8_t row[7]; } font[] = {
        {'-', {0,0,0,31,0,0,0}}, {'.',{0,0,0,0,0,6,6}}, {':',{0,6,6,0,6,6,0}},
        {'0',{14,17,19,21,25,17,14}}, {'1',{4,12,4,4,4,4,14}},
        {'2',{14,17,1,2,4,8,31}}, {'3',{30,1,1,14,1,1,30}},
        {'4',{2,6,10,18,31,2,2}}, {'5',{31,16,16,30,1,1,30}},
        {'6',{14,16,16,30,17,17,14}}, {'7',{31,1,2,4,8,8,8}},
        {'8',{14,17,17,14,17,17,14}}, {'9',{14,17,17,15,1,1,14}},
        {'A',{14,17,17,31,17,17,17}}, {'B',{30,17,17,30,17,17,30}},
        {'C',{14,17,16,16,16,17,14}}, {'D',{30,17,17,17,17,17,30}},
        {'E',{31,16,16,30,16,16,31}}, {'F',{31,16,16,30,16,16,16}},
        {'G',{14,17,16,23,17,17,15}}, {'H',{17,17,17,31,17,17,17}},
        {'I',{14,4,4,4,4,4,14}}, {'J',{7,2,2,2,18,18,12}},
        {'K',{17,18,20,24,20,18,17}}, {'L',{16,16,16,16,16,16,31}},
        {'M',{17,27,21,21,17,17,17}}, {'N',{17,25,21,19,17,17,17}},
        {'O',{14,17,17,17,17,17,14}}, {'P',{30,17,17,30,16,16,16}},
        {'Q',{14,17,17,17,21,18,13}}, {'R',{30,17,17,30,20,18,17}},
        {'S',{15,16,16,14,1,1,30}}, {'T',{31,4,4,4,4,4,4}},
        {'U',{17,17,17,17,17,17,14}}, {'V',{17,17,17,17,17,10,4}},
        {'W',{17,17,17,21,21,21,10}}, {'X',{17,17,10,4,10,17,17}},
        {'Y',{17,17,10,4,4,4,4}}, {'Z',{31,1,2,4,8,16,31}},
    };
    char c = (char)toupper((unsigned char)input);
    for (size_t i = 0; i < sizeof(font) / sizeof(font[0]); ++i) {
        if (font[i].c == c) return font[i].row;
    }
    return blank;
}

static void lcd_text(const char *text, int x, int y, int scale, uint16_t color) {
    uint16_t pixel = __builtin_bswap16(color);
    for (; *text && x + (6 * scale) < 128; ++text, x += 6 * scale) {
        const uint8_t *rows = glyph(*text);
        for (int row = 0; row < 7; ++row) for (int col = 0; col < 5; ++col) {
            if (!(rows[row] & (1U << (4 - col)))) continue;
            int px = x + col * scale, py = y + row * scale;
            lcd_window(px, py, px + scale - 1, py + scale - 1);
            gpio_set_level(AIPI_LCD_DC, 1);
            for (int n = 0; n < scale * scale; ++n) {
                spi_transaction_t tx = {.length = 16, .tx_buffer = &pixel};
                ESP_ERROR_CHECK(spi_device_polling_transmit(lcd, &tx));
            }
        }
    }
}

/* Pushes the renderer's framebuffer to the panel.
 *
 * The framebuffer is host-order RGB565 while the ST7735 expects big-endian, so
 * bytes are swapped on the way out. Swapping through a small scratch buffer
 * costs 4 KB and sixteen transfers a frame, rather than a second full-size
 * buffer or a per-line transaction for every one of 128 rows. */
#define FLUSH_CHUNK_PIXELS 2048
static uint16_t flush_scratch[FLUSH_CHUNK_PIXELS];

static void lcd_flush(const uint16_t *framebuffer) {
    if (!lcd || !framebuffer) return;
    lcd_window(0, 0, DISPLAY_W - 1, DISPLAY_H - 1);
    const int total = DISPLAY_W * DISPLAY_H;
    for (int offset = 0; offset < total; offset += FLUSH_CHUNK_PIXELS) {
        int count = total - offset;
        if (count > FLUSH_CHUNK_PIXELS) count = FLUSH_CHUNK_PIXELS;
        for (int i = 0; i < count; ++i) {
            flush_scratch[i] = __builtin_bswap16(framebuffer[offset + i]);
        }
        spi_transaction_t tx = {
            .length = (size_t)count * 16,
            .tx_buffer = flush_scratch,
        };
        if (spi_device_polling_transmit(lcd, &tx) != ESP_OK) return;
    }
}

esp_err_t bringup_display_init(void) {
    spi_bus_config_t bus = {
        .mosi_io_num = AIPI_LCD_MOSI, .miso_io_num = -1, .sclk_io_num = AIPI_LCD_SCLK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 128 * 128 * 2,
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO), TAG, "spi bus");
    spi_device_interface_config_t dev = {
        .clock_speed_hz = 20 * 1000 * 1000, .mode = 0, .spics_io_num = AIPI_LCD_CS,
        .queue_size = 1,
    };
    ESP_RETURN_ON_ERROR(spi_bus_add_device(SPI2_HOST, &dev, &lcd), TAG, "lcd device");
    gpio_config_t outputs = {
        .pin_bit_mask = (1ULL << AIPI_LCD_DC) | (1ULL << AIPI_LCD_RESET) |
                        (1ULL << AIPI_LCD_BACKLIGHT), .mode = GPIO_MODE_OUTPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&outputs), TAG, "lcd gpio");
    gpio_set_level(AIPI_LCD_BACKLIGHT, 0);
    gpio_set_level(AIPI_LCD_RESET, 0); vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(AIPI_LCD_RESET, 1); vTaskDelay(pdMS_TO_TICKS(120));
    ESP_RETURN_ON_ERROR(lcd_tx(0x01, NULL, 0), TAG, "software reset");
    vTaskDelay(pdMS_TO_TICKS(150));
    ESP_RETURN_ON_ERROR(lcd_tx(0x11, NULL, 0), TAG, "sleep out");
    vTaskDelay(pdMS_TO_TICKS(120));
    uint8_t format = 0x05;
    ESP_RETURN_ON_ERROR(lcd_tx(0x3a, &format, 1), TAG, "rgb565");
    uint8_t rotation = 0x60;
    ESP_RETURN_ON_ERROR(lcd_tx(0x36, &rotation, 1), TAG, "rotation");
    ESP_RETURN_ON_ERROR(lcd_tx(0x21, NULL, 0), TAG, "invert on");
    ESP_RETURN_ON_ERROR(lcd_tx(0x29, NULL, 0), TAG, "display on");
    vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(AIPI_LCD_BACKLIGHT, 1);
    lcd_fill(0x0000);
    display_set_flush(lcd_flush);
    return ESP_OK;
}

void bringup_display_status(const char *line1, const char *line2, const char *line3) {
    if (!lcd) return;
    /* Once the animated interface owns the panel, the legacy text screens are
     * suppressed: two writers would tear against each other. Their content is
     * still visible in the serial log. */
    if (display_controller_active()) return;
    lcd_fill(0x0000);
    lcd_text(line1, 7, 12, 2, 0xffff);
    lcd_text(line2, 7, 58, 1, 0x07ff);
    lcd_text(line3, 7, 78, 1, 0x07e0);
}

void bringup_display_status4(const char *line1, const char *line2, const char *line3,
                             const char *line4) {
    if (!lcd) return;
    if (display_controller_active()) return;
    lcd_fill(0x0000);
    lcd_text(line1, 7, 8, 2, 0xffff);
    lcd_text(line2, 7, 48, 1, 0x07ff);
    lcd_text(line3, 7, 66, 1, 0xffff);
    lcd_text(line4, 7, 84, 1, 0x07e0);
}

static void button_task(void *unused) {
    (void)unused;
    int stable = gpio_get_level(AIPI_BUTTON), prior = stable, count = 0;
    ESP_LOGI(TAG, "button ready gpio=%d active_low=1", AIPI_BUTTON);
    while (true) {
        int sample = gpio_get_level(AIPI_BUTTON);
        if (sample == stable) count = 0;
        else if (++count >= 3) {
            stable = sample; count = 0;
            if (stable != prior) {
                ESP_LOGI(TAG, "%s", stable ? "BUTTON_UP" : "BUTTON_DOWN");
                if (!stable) {
                    /* Online, the press starts a voice turn on Jarvis. Offline,
                     * it falls back to the local speaker self-test so the
                     * button still proves the audio path with no network. */
                    if (!local_connection_button_pressed() &&
                        audio_output_manual_test_enabled()) {
                        esp_err_t result = audio_output_test_tone();
                        if (result != ESP_OK) {
                            ESP_LOGE(TAG, "speaker test failed safely: %s",
                                     esp_err_to_name(result));
                            bringup_display_status("JARVIS", "ONLINE", "AUDIO: ERROR");
                        }
                    }
                }
                prior = stable;
            }
        }
        /* Drive the playback stall watchdog from this existing periodic task
         * rather than spawning another one. Without a caller the watchdog is
         * dead code and a wedged sender could hold the amplifier open. */
        audio_playback_poll_timeout();
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

esp_err_t bringup_button_start(void) {
    gpio_config_t input = {
        .pin_bit_mask = 1ULL << AIPI_BUTTON, .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&input), TAG, "button gpio");
    /* Tone generation uses bounded stack PCM buffers. Keep ample headroom so a
       button press cannot corrupt the I2S/GDMA driver state. */
    return xTaskCreate(button_task, "aipi_button", 6144, NULL, 5, NULL) == pdPASS
        ? ESP_OK : ESP_ERR_NO_MEM;
}

bool bringup_codec_probe(void) {
    gpio_config_t amp = {
        .pin_bit_mask = 1ULL << AIPI_SPEAKER_ENABLE, .mode = GPIO_MODE_OUTPUT,
    };
    if (gpio_config(&amp) != ESP_OK) return false;
    gpio_set_level(AIPI_SPEAKER_ENABLE, 0);
    ESP_LOGI(TAG, "speaker amplifier forced OFF for stage-1 validation");
    return es8311_codec_probe();
}
