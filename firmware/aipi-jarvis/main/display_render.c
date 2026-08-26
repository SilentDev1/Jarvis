#include "display_render.h"

#include <stdlib.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"

#define TAG "jarvis_display"

/* Framebuffer lives in internal DMA-capable RAM: 32 KB, pushed in one
 * transfer. PSRAM would work but adds latency on every pixel write, and the
 * renderer touches the buffer far more often than it flushes it. */
static uint16_t *framebuffer;
static display_flush_fn flush_cb;

/* Fixed-point sine, 256 steps per revolution, amplitude 1024. Avoids float
 * trigonometry in the render loop. */
static const int16_t SIN_TABLE[256] = {
       0,   25,   50,   75,  100,  125,  150,  175,  200,  224,  249,  273,  297,  321,  345,  369,
     392,  415,  438,  460,  483,  505,  526,  548,  569,  590,  610,  630,  650,  669,  688,  706,
     724,  742,  759,  775,  792,  807,  822,  837,  851,  865,  878,  891,  903,  915,  926,  936,
     946,  955,  964,  972,  980,  987,  993,  999, 1004, 1009, 1013, 1016, 1019, 1021, 1023, 1024,
    1024, 1024, 1023, 1021, 1019, 1016, 1013, 1009, 1004,  999,  993,  987,  980,  972,  964,  955,
     946,  936,  926,  915,  903,  891,  878,  865,  851,  837,  822,  807,  792,  775,  759,  742,
     724,  706,  688,  669,  650,  630,  610,  590,  569,  548,  526,  505,  483,  460,  438,  415,
     392,  369,  345,  321,  297,  273,  249,  224,  200,  175,  150,  125,  100,   75,   50,   25,
       0,  -25,  -50,  -75, -100, -125, -150, -175, -200, -224, -249, -273, -297, -321, -345, -369,
    -392, -415, -438, -460, -483, -505, -526, -548, -569, -590, -610, -630, -650, -669, -688, -706,
    -724, -742, -759, -775, -792, -807, -822, -837, -851, -865, -878, -891, -903, -915, -926, -936,
    -946, -955, -964, -972, -980, -987, -993, -999,-1004,-1009,-1013,-1016,-1019,-1021,-1023,-1024,
   -1024,-1024,-1023,-1021,-1019,-1016,-1013,-1009,-1004, -999, -993, -987, -980, -972, -964, -955,
    -946, -936, -926, -915, -903, -891, -878, -865, -851, -837, -822, -807, -792, -775, -759, -742,
    -724, -706, -688, -669, -650, -630, -610, -590, -569, -548, -526, -505, -483, -460, -438, -415,
    -392, -369, -345, -321, -297, -273, -249, -224, -200, -175, -150, -125, -100,  -75,  -50,  -25,
};

static inline int fx_sin(uint8_t a) { return SIN_TABLE[a]; }
static inline int fx_cos(uint8_t a) { return SIN_TABLE[(uint8_t)(a + 64)]; }

bool display_render_ready(void) { return framebuffer != NULL; }

bool display_render_init(void) {
    if (framebuffer) return true;
    framebuffer = heap_caps_malloc(DISPLAY_W * DISPLAY_H * sizeof(uint16_t),
                                   MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!framebuffer) {
        /* Not fatal: the caller keeps using the plain text screens. Voice and
         * network matter more than animation. */
        ESP_LOGE(TAG, "framebuffer allocation failed; animation disabled");
        return false;
    }
    memset(framebuffer, 0, DISPLAY_W * DISPLAY_H * sizeof(uint16_t));
    ESP_LOGI(TAG, "arc-core renderer ready (%d bytes framebuffer)",
             DISPLAY_W * DISPLAY_H * (int)sizeof(uint16_t));
    return true;
}

void display_set_flush(display_flush_fn flush) { flush_cb = flush; }

void display_present(void) {
    if (framebuffer && flush_cb) flush_cb(framebuffer);
}

display_color_t display_rgb(uint8_t r, uint8_t g, uint8_t b) {
    return (display_color_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

display_color_t display_scale(display_color_t color, uint8_t intensity) {
    int r = ((color >> 11) & 0x1F) * intensity / 255;
    int g = ((color >> 5) & 0x3F) * intensity / 255;
    int b = (color & 0x1F) * intensity / 255;
    return (display_color_t)((r << 11) | (g << 5) | b);
}

void display_clear(display_color_t color) {
    if (!framebuffer) return;
    if (color == 0) {
        memset(framebuffer, 0, DISPLAY_W * DISPLAY_H * sizeof(uint16_t));
        return;
    }
    for (int i = 0; i < DISPLAY_W * DISPLAY_H; ++i) framebuffer[i] = color;
}

void display_pixel(int x, int y, display_color_t color) {
    if (!framebuffer) return;
    if ((unsigned)x >= DISPLAY_W || (unsigned)y >= DISPLAY_H) return;
    framebuffer[y * DISPLAY_W + x] = color;
}

/* Additive plot so overlapping glow elements brighten rather than overwrite,
 * which is what makes the core read as light rather than paint. */
static void plot_add(int x, int y, display_color_t color) {
    if (!framebuffer) return;
    if ((unsigned)x >= DISPLAY_W || (unsigned)y >= DISPLAY_H) return;
    uint16_t existing = framebuffer[y * DISPLAY_W + x];
    int r = ((existing >> 11) & 0x1F) + ((color >> 11) & 0x1F);
    int g = ((existing >> 5) & 0x3F) + ((color >> 5) & 0x3F);
    int b = (existing & 0x1F) + (color & 0x1F);
    if (r > 0x1F) r = 0x1F;
    if (g > 0x3F) g = 0x3F;
    if (b > 0x1F) b = 0x1F;
    framebuffer[y * DISPLAY_W + x] = (uint16_t)((r << 11) | (g << 5) | b);
}

void display_core(int cx, int cy, int radius, int glow, display_color_t color) {
    if (!framebuffer || radius <= 0) return;
    int outer = radius + glow;
    int outer2 = outer * outer;
    int core2 = radius * radius;
    for (int y = cy - outer; y <= cy + outer; ++y) {
        if ((unsigned)y >= DISPLAY_H) continue;
        int dy = y - cy;
        for (int x = cx - outer; x <= cx + outer; ++x) {
            if ((unsigned)x >= DISPLAY_W) continue;
            int dx = x - cx;
            int d2 = dx * dx + dy * dy;
            if (d2 > outer2) continue;
            uint8_t intensity;
            if (d2 <= core2) {
                intensity = 255;
            } else if (glow > 0) {
                /* Linear falloff in squared space is cheap and looks close
                 * enough to a glow at this size. */
                intensity = (uint8_t)(255 - (d2 - core2) * 255 / (outer2 - core2));
            } else {
                continue;
            }
            plot_add(x, y, display_scale(color, intensity));
        }
    }
}

static void stroke_arc(int cx, int cy, int radius, int thickness,
                       uint8_t from, uint8_t to, display_color_t color) {
    /* Step finely enough that the stroke has no gaps at this radius. */
    for (uint8_t a = from;; ++a) {
        int c = fx_cos(a), s = fx_sin(a);
        for (int t = 0; t < thickness; ++t) {
            int r = radius + t;
            plot_add(cx + (c * r >> 10), cy + (s * r >> 10), color);
        }
        if (a == to) break;
    }
}

void display_ring(int cx, int cy, int radius, int thickness, display_color_t color) {
    if (radius <= 0) return;
    stroke_arc(cx, cy, radius, thickness, 0, 255, color);
}

void display_segments(int cx, int cy, int radius, int thickness, int segments,
                      int gap_percent, uint8_t angle, display_color_t color) {
    if (radius <= 0 || segments <= 0) return;
    int span = 256 / segments;
    int gap = span * gap_percent / 100;
    int draw = span - gap;
    if (draw < 1) draw = 1;
    for (int i = 0; i < segments; ++i) {
        uint8_t from = (uint8_t)(angle + i * span);
        uint8_t to = (uint8_t)(from + draw - 1);
        stroke_arc(cx, cy, radius, thickness, from, to, color);
    }
}

void display_ticks(int cx, int cy, int radius, int length, int count,
                   uint8_t angle, display_color_t color) {
    if (count <= 0) return;
    int step = 256 / count;
    for (int i = 0; i < count; ++i) {
        uint8_t a = (uint8_t)(angle + i * step);
        int c = fx_cos(a), s = fx_sin(a);
        for (int t = 0; t < length; ++t) {
            int r = radius + t;
            plot_add(cx + (c * r >> 10), cy + (s * r >> 10), color);
        }
    }
}

void display_progress_ring(int cx, int cy, int radius, int thickness,
                           int percent, display_color_t color) {
    if (percent <= 0 || radius <= 0) return;
    if (percent > 100) percent = 100;
    /* Start at the top and sweep clockwise, which is what people expect a
     * progress ring to do. */
    uint8_t start = 192;
    uint8_t sweep = (uint8_t)(percent * 255 / 100);
    stroke_arc(cx, cy, radius, thickness, start, (uint8_t)(start + sweep), color);
}

void display_level_bars(int cx, int cy, int level, display_color_t color) {
    /* Five bars either side; height follows the level with a fixed shape so
     * the middle bars move most, like a simple meter. */
    static const int shape[5] = {40, 70, 100, 70, 40};
    if (level < 0) level = 0;
    if (level > 100) level = 100;
    for (int i = 0; i < 5; ++i) {
        int height = level * shape[i] / 100 * 18 / 100;
        if (height < 1) height = 1;
        int offset = 44 + i * 5;
        for (int y = cy - height; y <= cy + height; ++y) {
            plot_add(cx - offset, y, color);
            plot_add(cx - offset + 1, y, color);
            plot_add(cx + offset, y, color);
            plot_add(cx + offset - 1, y, color);
        }
    }
}

/* 5x7 font. Reuses the same glyph shapes as the original status screens so
 * the two paths cannot disagree about what a character looks like. */
static const struct { char c; uint8_t row[7]; } FONT[] = {
    {'A', {0x0E,0x11,0x11,0x1F,0x11,0x11,0x11}}, {'B', {0x1E,0x11,0x1E,0x11,0x11,0x11,0x1E}},
    {'C', {0x0E,0x11,0x10,0x10,0x10,0x11,0x0E}}, {'D', {0x1E,0x11,0x11,0x11,0x11,0x11,0x1E}},
    {'E', {0x1F,0x10,0x1E,0x10,0x10,0x10,0x1F}}, {'F', {0x1F,0x10,0x1E,0x10,0x10,0x10,0x10}},
    {'G', {0x0E,0x11,0x10,0x17,0x11,0x11,0x0F}}, {'H', {0x11,0x11,0x1F,0x11,0x11,0x11,0x11}},
    {'I', {0x0E,0x04,0x04,0x04,0x04,0x04,0x0E}}, {'J', {0x07,0x02,0x02,0x02,0x02,0x12,0x0C}},
    {'K', {0x11,0x12,0x14,0x18,0x14,0x12,0x11}}, {'L', {0x10,0x10,0x10,0x10,0x10,0x10,0x1F}},
    {'M', {0x11,0x1B,0x15,0x15,0x11,0x11,0x11}}, {'N', {0x11,0x19,0x15,0x13,0x11,0x11,0x11}},
    {'O', {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E}}, {'P', {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10}},
    {'Q', {0x0E,0x11,0x11,0x11,0x15,0x12,0x0D}}, {'R', {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11}},
    {'S', {0x0F,0x10,0x0E,0x01,0x01,0x11,0x0E}}, {'T', {0x1F,0x04,0x04,0x04,0x04,0x04,0x04}},
    {'U', {0x11,0x11,0x11,0x11,0x11,0x11,0x0E}}, {'V', {0x11,0x11,0x11,0x11,0x11,0x0A,0x04}},
    {'W', {0x11,0x11,0x11,0x15,0x15,0x1B,0x11}}, {'X', {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11}},
    {'Y', {0x11,0x11,0x0A,0x04,0x04,0x04,0x04}}, {'Z', {0x1F,0x01,0x02,0x04,0x08,0x10,0x1F}},
    {'0', {0x0E,0x11,0x13,0x15,0x19,0x11,0x0E}}, {'1', {0x04,0x0C,0x04,0x04,0x04,0x04,0x0E}},
    {'2', {0x0E,0x11,0x01,0x02,0x04,0x08,0x1F}}, {'3', {0x1F,0x02,0x04,0x02,0x01,0x11,0x0E}},
    {'4', {0x02,0x06,0x0A,0x12,0x1F,0x02,0x02}}, {'5', {0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E}},
    {'6', {0x06,0x08,0x10,0x1E,0x11,0x11,0x0E}}, {'7', {0x1F,0x01,0x02,0x04,0x08,0x08,0x08}},
    {'8', {0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E}}, {'9', {0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C}},
    {'.', {0x00,0x00,0x00,0x00,0x00,0x0C,0x0C}}, {'-', {0x00,0x00,0x00,0x1F,0x00,0x00,0x00}},
    {':', {0x00,0x0C,0x0C,0x00,0x0C,0x0C,0x00}}, {'%', {0x19,0x1A,0x02,0x04,0x08,0x0B,0x13}},
    {' ', {0x00,0x00,0x00,0x00,0x00,0x00,0x00}},
};

static const uint8_t *glyph_for(char input) {
    char c = (input >= 'a' && input <= 'z') ? (char)(input - 32) : input;
    for (size_t i = 0; i < sizeof(FONT) / sizeof(FONT[0]); ++i) {
        if (FONT[i].c == c) return FONT[i].row;
    }
    return NULL;
}

void display_text(const char *text, int x, int y, int scale, display_color_t color) {
    if (!framebuffer || !text) return;
    int cursor = x;
    for (const char *p = text; *p; ++p) {
        const uint8_t *rows = glyph_for(*p);
        if (rows) {
            for (int row = 0; row < 7; ++row) {
                for (int col = 0; col < 5; ++col) {
                    if (!(rows[row] & (1 << (4 - col)))) continue;
                    for (int sy = 0; sy < scale; ++sy) {
                        for (int sx = 0; sx < scale; ++sx) {
                            display_pixel(cursor + col * scale + sx,
                                          y + row * scale + sy, color);
                        }
                    }
                }
            }
        }
        cursor += 6 * scale;
    }
}

int display_text_centered(const char *text, int y, int scale, display_color_t color) {
    if (!text) return 0;
    int width = 0;
    for (const char *p = text; *p; ++p) width += 6 * scale;
    if (width > 0) width -= scale;   /* trailing advance is not ink */
    int x = (DISPLAY_W - width) / 2;
    if (x < 0) x = 0;
    display_text(text, x, y, scale, color);
    return x;
}
