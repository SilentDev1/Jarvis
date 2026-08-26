#include "arc_light.h"

#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"

#define TAG "jarvis_arc"

/* Onboard single-pixel WS2812. Corroborated by the known-working AiPi Lite
 * reference firmware ("WS2812 on GPIO46, 1 pixel") and by this project's own
 * hardware notes. It is wired and powered by the board, so driving it needs no
 * external circuitry, no MOSFET and no separate supply.
 *
 * GPIO46 is a strapping pin on the ESP32-S3, sampled only at reset; driving it
 * as an output afterwards is normal and is what the reference does. */
#define ARC_ONBOARD_GPIO 46
#define ARC_PIXELS 1

/* 20 Hz. Fast enough for smooth breathing and for the light to track speech,
 * slow enough to stay irrelevant next to audio and networking. */
#define ARC_INTERVAL_MS 50

typedef struct { uint8_t r, g, b; } arc_rgb_t;

static led_strip_handle_t strip;
static arc_backend_t backend = ARC_BACKEND_NONE;
static volatile bool enabled;
static volatile bool quiet_hours;
static volatile jarvis_visual_t state = JARVIS_VISUAL_BOOT;
static volatile int audio_level;
static volatile int idle_brightness = ARC_DEFAULT_IDLE_BRIGHTNESS;
static volatile int active_brightness = ARC_DEFAULT_ACTIVE_BRIGHTNESS;
static bool running;

bool arc_light_available(void) { return backend != ARC_BACKEND_NONE && strip != NULL; }
bool arc_light_enabled(void) { return enabled && arc_light_available(); }

static int clamp(int value, int low, int high) {
    return value < low ? low : (value > high ? high : value);
}

/* Colours mirror the display palette so the light and the screen agree. */
static arc_rgb_t colour_for(jarvis_visual_t visual) {
    switch (visual) {
    case JARVIS_VISUAL_IDLE:       return (arc_rgb_t){ 40, 150, 220};
    case JARVIS_VISUAL_VISITOR:    return (arc_rgb_t){ 90, 210, 255};
    case JARVIS_VISUAL_LISTENING:  return (arc_rgb_t){ 60, 230, 120};
    case JARVIS_VISUAL_PROCESSING: return (arc_rgb_t){255, 190,  60};
    case JARVIS_VISUAL_SPEAKING:   return (arc_rgb_t){ 90, 200, 255};
    case JARVIS_VISUAL_CONNECTING: return (arc_rgb_t){255, 170,  40};
    case JARVIS_VISUAL_UPDATING:   return (arc_rgb_t){ 90, 200, 255};
    case JARVIS_VISUAL_OFFLINE:    return (arc_rgb_t){170,  40,  40};
    case JARVIS_VISUAL_ERROR:      return (arc_rgb_t){255,  90,  20};
    case JARVIS_VISUAL_BOOT:
    default:                       return (arc_rgb_t){ 60, 170, 235};
    }
}

/* Triangle wave; smooth enough at 20 Hz and cheaper than a sine lookup. */
static int wave(uint32_t frame, int period, int low, int high) {
    int phase = (int)(frame % (uint32_t)period);
    int half = period / 2;
    int position = phase < half ? phase : period - phase;
    return low + (high - low) * position / half;
}

/* Brightness percentage for the current state, before quiet-hours scaling. */
static int brightness_for(jarvis_visual_t visual, uint32_t frame) {
    int idle = clamp(idle_brightness, 0, ARC_MAX_BRIGHTNESS);
    int active = clamp(active_brightness, 0, ARC_MAX_BRIGHTNESS);
    int level = clamp(audio_level, 0, 100);

    /* Each state occupies a band between the owner's idle and active
     * settings, so raising or lowering brightness scales the whole scheme
     * rather than flattening the differences between states. */
    switch (visual) {
    case JARVIS_VISUAL_IDLE:
        /* Calm and clearly the quietest state. */
        return wave(frame, 120, idle, idle + (active - idle) / 8);
    case JARVIS_VISUAL_VISITOR:
        /* Wakes noticeably: this is the terminal noticing someone. */
        return wave(frame, 40, idle + (active - idle) / 2, active * 4 / 5);
    case JARVIS_VISUAL_LISTENING:
        /* Breathing floor with the input level layered on top. */
        return clamp(wave(frame, 60, idle + (active - idle) / 4, active * 3 / 5)
                     + level * active / 400,
                     0, ARC_MAX_BRIGHTNESS);
    case JARVIS_VISUAL_PROCESSING:
        /* Faster than listening, dimmer than speech: visibly working. */
        return wave(frame, 24, idle + (active - idle) / 3, active * 3 / 4);
    case JARVIS_VISUAL_SPEAKING:
        /* Audio reactive across the widest band, with a floor so it never goes
         * dark mid-sentence. */
        return clamp(idle + (active - idle) * level / 100, 0, ARC_MAX_BRIGHTNESS);
    case JARVIS_VISUAL_CONNECTING:
        return wave(frame, 80, idle / 2, active / 2);
    case JARVIS_VISUAL_UPDATING:
        return wave(frame, 30, idle, active);
    case JARVIS_VISUAL_OFFLINE:
        /* Distinctive slow blink rather than darkness, so an offline terminal
         * is visibly offline rather than looking dead. */
        return (frame % 60) < 6 ? idle : 0;
    case JARVIS_VISUAL_ERROR:
        /* Deliberately a slow double blink, not a strobe. */
        return ((frame % 40) < 5 || ((frame % 40) >= 10 && (frame % 40) < 15))
               ? active : idle / 3;
    case JARVIS_VISUAL_BOOT:
    default:
        return frame < 20 ? (int)frame * active / 20 : active;
    }
}

static void apply(jarvis_visual_t visual, uint32_t frame) {
    if (!arc_light_available()) return;
    if (!enabled) {
        led_strip_clear(strip);
        return;
    }
    int percent = brightness_for(visual, frame);
    if (quiet_hours) {
        /* Dimmed, not extinguished: the indicator still has a job at night. */
        percent = percent * ARC_QUIET_SCALE_PERCENT / 100;
    }
    percent = clamp(percent, 0, ARC_MAX_BRIGHTNESS);
    arc_rgb_t colour = colour_for(visual);
    led_strip_set_pixel(strip,
                        0,
                        (uint32_t)colour.r * percent / 100,
                        (uint32_t)colour.g * percent / 100,
                        (uint32_t)colour.b * percent / 100);
    led_strip_refresh(strip);
}

static void arc_task(void *unused) {
    (void)unused;
    uint32_t frame = 0;
    TickType_t last = xTaskGetTickCount();
    while (running) {
        apply(state, frame++);
        vTaskDelayUntil(&last, pdMS_TO_TICKS(ARC_INTERVAL_MS));
    }
    arc_light_off();
    vTaskDelete(NULL);
}

esp_err_t arc_light_init(arc_backend_t requested) {
    if (running) return ESP_OK;
    if (requested == ARC_BACKEND_NONE) {
        backend = ARC_BACKEND_NONE;
        ESP_LOGI(TAG, "arc light backend: none");
        return ESP_OK;
    }

    led_strip_config_t config = {
        .strip_gpio_num = ARC_ONBOARD_GPIO,
        .max_leds = ARC_PIXELS,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
    };
    led_strip_rmt_config_t rmt = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
    };
    esp_err_t result = led_strip_new_rmt_device(&config, &rmt, &strip);
    if (result != ESP_OK) {
        /* Best effort, like the display: the terminal works without a light. */
        ESP_LOGW(TAG, "onboard LED unavailable: %s", esp_err_to_name(result));
        backend = ARC_BACKEND_NONE;
        return result;
    }
    backend = requested;
    /* Start dark. A light that flashes on at boot before anyone has asked for
     * it is exactly what the owner setting exists to prevent. */
    led_strip_clear(strip);

    running = true;
    if (xTaskCreate(arc_task, "jarvis_arc", 2560, NULL, 2, NULL) != pdPASS) {
        running = false;
        ESP_LOGW(TAG, "arc light task could not start");
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "arc light ready on onboard WS2812 (GPIO%d), disabled until enabled",
             ARC_ONBOARD_GPIO);
    return ESP_OK;
}

void arc_light_set_enabled(bool value) {
    enabled = value;
    if (!value) arc_light_off();
}

void arc_light_set_state(jarvis_visual_t visual) { state = visual; }
void arc_light_set_level(int level) { audio_level = clamp(level, 0, 100); }

void arc_light_set_brightness(int idle_percent, int active_percent) {
    idle_brightness = clamp(idle_percent, 0, ARC_MAX_BRIGHTNESS);
    active_brightness = clamp(active_percent, 0, ARC_MAX_BRIGHTNESS);
}

void arc_light_set_quiet(bool value) { quiet_hours = value; }

void arc_light_off(void) {
    if (strip) led_strip_clear(strip);
}
