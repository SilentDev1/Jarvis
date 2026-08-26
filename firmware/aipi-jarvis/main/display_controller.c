#include "display_controller.h"

#include <stdio.h>
#include <string.h>

#include "display_render.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define TAG "jarvis_visual"

/* 20 FPS. Comfortably smooth for this artwork and leaves the CPU and the SPI
 * bus mostly idle for audio and networking, which matter more. */
#define FRAME_INTERVAL_MS 50

/* Layout. The core sits slightly below centre so the JARVIS header and the
 * status line both have room without crowding it. */
#define CORE_CX DISPLAY_CX
#define CORE_CY 66
#define HEADER_Y 8
#define STATUS_Y 108

static volatile jarvis_visual_t current = JARVIS_VISUAL_BOOT;
static volatile int audio_level;
static volatile int ota_percent;
static char ota_label[16];
static char status_override[20];
static bool running;
static TaskHandle_t render_task_handle;

typedef struct {
    display_color_t core;
    display_color_t ring;
    display_color_t accent;
    const char *status;
} visual_style_t;

/* Palette follows the agreed colour language: cyan when well, amber while
 * working, green while listening, red when something is wrong. */
static visual_style_t style_for(jarvis_visual_t visual) {
    switch (visual) {
    case JARVIS_VISUAL_BOOT:
        return (visual_style_t){display_rgb(80, 200, 255), display_rgb(0, 120, 200),
                                display_rgb(0, 80, 140), "BOOTING"};
    case JARVIS_VISUAL_CONNECTING:
        return (visual_style_t){display_rgb(255, 190, 60), display_rgb(200, 130, 0),
                                display_rgb(120, 80, 0), "CONNECTING"};
    case JARVIS_VISUAL_IDLE:
        return (visual_style_t){display_rgb(60, 170, 235), display_rgb(0, 90, 160),
                                display_rgb(0, 50, 90), "IDLE"};
    case JARVIS_VISUAL_VISITOR:
        return (visual_style_t){display_rgb(120, 230, 255), display_rgb(0, 160, 230),
                                display_rgb(0, 90, 140), "VISITOR"};
    case JARVIS_VISUAL_LISTENING:
        return (visual_style_t){display_rgb(90, 255, 140), display_rgb(0, 190, 90),
                                display_rgb(0, 110, 50), "LISTENING"};
    case JARVIS_VISUAL_PROCESSING:
        return (visual_style_t){display_rgb(255, 210, 90), display_rgb(220, 150, 0),
                                display_rgb(130, 90, 0), "THINKING"};
    case JARVIS_VISUAL_SPEAKING:
        return (visual_style_t){display_rgb(120, 220, 255), display_rgb(0, 150, 240),
                                display_rgb(0, 80, 150), "SPEAKING"};
    case JARVIS_VISUAL_OFFLINE:
        return (visual_style_t){display_rgb(150, 40, 40), display_rgb(90, 20, 20),
                                display_rgb(50, 10, 10), "OFFLINE"};
    case JARVIS_VISUAL_UPDATING:
        return (visual_style_t){display_rgb(120, 220, 255), display_rgb(0, 150, 240),
                                display_rgb(0, 80, 150), "UPDATING"};
    case JARVIS_VISUAL_ERROR:
    default:
        return (visual_style_t){display_rgb(255, 120, 40), display_rgb(190, 70, 10),
                                display_rgb(110, 40, 0), "ERROR"};
    }
}

/* Triangle wave, used for breathing. Smooth enough at 20 FPS and cheaper than
 * a sine lookup per frame. */
static int breathe(uint32_t frame, int period, int low, int high) {
    int phase = (int)(frame % (uint32_t)period);
    int half = period / 2;
    int position = phase < half ? phase : period - phase;
    return low + (high - low) * position / half;
}

static void render_frame(uint32_t frame) {
    jarvis_visual_t visual = current;
    visual_style_t style = style_for(visual);
    display_clear(0);

    int level = audio_level;
    if (level < 0) level = 0;
    if (level > 100) level = 100;

    /* Core size and brightness: audio-reactive while speaking or listening,
     * a slow breath otherwise. */
    int core_radius = 9;
    int glow = 10;
    uint8_t core_intensity = 220;

    switch (visual) {
    case JARVIS_VISUAL_SPEAKING:
        core_radius = 9 + level * 6 / 100;
        glow = 10 + level * 10 / 100;
        core_intensity = (uint8_t)(170 + level * 85 / 100);
        break;
    case JARVIS_VISUAL_LISTENING:
        core_radius = 8 + level * 4 / 100;
        glow = 12;
        core_intensity = (uint8_t)(160 + level * 60 / 100);
        break;
    case JARVIS_VISUAL_IDLE:
        core_radius = 8;
        glow = breathe(frame, 120, 8, 14);
        core_intensity = (uint8_t)breathe(frame, 120, 140, 200);
        break;
    case JARVIS_VISUAL_OFFLINE:
        core_radius = 6;
        glow = breathe(frame, 200, 3, 6);
        core_intensity = (uint8_t)breathe(frame, 200, 50, 90);
        break;
    case JARVIS_VISUAL_VISITOR:
        core_radius = 10 + breathe(frame, 40, 0, 3);
        glow = breathe(frame, 40, 12, 20);
        core_intensity = 255;
        break;
    case JARVIS_VISUAL_PROCESSING:
        core_radius = 9;
        glow = breathe(frame, 30, 8, 14);
        core_intensity = 230;
        break;
    case JARVIS_VISUAL_BOOT: {
        /* Assemble: a point that grows into the core over about a second. */
        int t = (int)(frame > 24 ? 24 : frame);
        core_radius = 1 + t * 8 / 24;
        glow = t * 12 / 24;
        core_intensity = (uint8_t)(60 + t * 195 / 24);
        break;
    }
    default:
        break;
    }

    display_core(CORE_CX, CORE_CY, core_radius, glow,
                 display_scale(style.core, core_intensity));

    /* Rings. Inner and outer counter-rotate while thinking, which reads as
     * work happening; elsewhere they drift slowly so the screen looks alive
     * without pulling the eye. */
    uint8_t inner_angle, outer_angle;
    switch (visual) {
    case JARVIS_VISUAL_PROCESSING:
        inner_angle = (uint8_t)(frame * 5);
        outer_angle = (uint8_t)(-(int)frame * 3);
        break;
    case JARVIS_VISUAL_CONNECTING:
        inner_angle = (uint8_t)(frame * 4);
        outer_angle = (uint8_t)(frame * 2);
        break;
    case JARVIS_VISUAL_VISITOR:
        inner_angle = (uint8_t)(frame * 3);
        outer_angle = (uint8_t)(-(int)frame * 2);
        break;
    default:
        inner_angle = (uint8_t)(frame / 2);
        outer_angle = (uint8_t)(-(int)frame / 3);
        break;
    }

    if (visual == JARVIS_VISUAL_BOOT && frame < 30) {
        /* Rings fade in after the core, so the boot reads as assembly. */
        uint8_t fade = (uint8_t)(frame > 12 ? (frame - 12) * 255 / 18 : 0);
        if (fade) {
            display_segments(CORE_CX, CORE_CY, 22, 2, 8, 30, inner_angle,
                             display_scale(style.ring, fade));
        }
    } else if (visual == JARVIS_VISUAL_UPDATING) {
        /* Outer ring becomes the progress indicator, core stays lit so the
         * device still looks alive mid-update. */
        display_ring(CORE_CX, CORE_CY, 30, 2, display_scale(style.accent, 90));
        display_progress_ring(CORE_CX, CORE_CY, 30, 3, ota_percent, style.core);
        display_segments(CORE_CX, CORE_CY, 22, 2, 8, 35, inner_angle,
                         display_scale(style.ring, 200));
    } else {
        display_segments(CORE_CX, CORE_CY, 22, 2, 8, 30, inner_angle, style.ring);
        display_segments(CORE_CX, CORE_CY, 30, 2, 12, 45, outer_angle,
                         display_scale(style.ring, 190));
        display_ticks(CORE_CX, CORE_CY, 36, 3, 16, outer_angle,
                      display_scale(style.accent, 220));
    }

    /* Level bars only where they mean something. */
    if (visual == JARVIS_VISUAL_SPEAKING || visual == JARVIS_VISUAL_LISTENING) {
        display_level_bars(CORE_CX, CORE_CY, level, display_scale(style.core, 210));
    }

    display_text_centered("JARVIS", HEADER_Y, 2, style.core);

    const char *status = status_override[0] ? status_override : style.status;
    char line[24];
    if (visual == JARVIS_VISUAL_UPDATING) {
        snprintf(line, sizeof(line), "%s %d%%",
                 ota_label[0] ? ota_label : "UPDATING", ota_percent);
        status = line;
    }
    display_text_centered(status, STATUS_Y, 1, display_scale(style.core, 230));

    display_present();
}

static void render_task(void *unused) {
    (void)unused;
    uint32_t frame = 0;
    TickType_t last = xTaskGetTickCount();
    while (running) {
        render_frame(frame++);
        /* Fixed cadence rather than a plain delay, so a slow frame does not
         * accumulate drift. */
        vTaskDelayUntil(&last, pdMS_TO_TICKS(FRAME_INTERVAL_MS));
    }
    render_task_handle = NULL;
    vTaskDelete(NULL);
}

esp_err_t display_controller_start(void) {
    if (running) return ESP_OK;
    if (!display_render_init()) {
        /* Best effort: the caller keeps the plain text screens. */
        return ESP_ERR_NO_MEM;
    }
    running = true;
    if (xTaskCreate(render_task, "jarvis_visual", 4096, NULL, 2,
                    &render_task_handle) != pdPASS) {
        running = false;
        ESP_LOGE(TAG, "render task could not start; animation disabled");
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "Jarvis visual interface running at %d FPS", 1000 / FRAME_INTERVAL_MS);
    return ESP_OK;
}

bool display_controller_active(void) { return running && display_render_ready(); }

void display_controller_set(jarvis_visual_t visual) { current = visual; }
jarvis_visual_t display_controller_get(void) { return current; }

void display_controller_set_level(int level) { audio_level = level; }

void display_controller_set_progress(int percent, const char *label) {
    ota_percent = percent;
    if (label) {
        snprintf(ota_label, sizeof(ota_label), "%s", label);
    } else {
        ota_label[0] = '\0';
    }
}

void display_controller_set_status(const char *status) {
    if (status) {
        snprintf(status_override, sizeof(status_override), "%s", status);
    } else {
        status_override[0] = '\0';
    }
}
