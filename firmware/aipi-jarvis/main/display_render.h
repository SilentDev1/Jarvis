#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Procedural renderer for the 128x128 arc-core interface.
 *
 * Everything is drawn into an in-RAM framebuffer and pushed to the panel in
 * one transfer. The previous code issued an SPI transaction per pixel for
 * text, which is fine for a static screen and far too slow to animate.
 *
 * No sqrt or atan2 per pixel: filled shapes compare squared distances, and
 * rings and arcs are walked parametrically from a fixed sine table. */

#define DISPLAY_W 128
#define DISPLAY_H 128
#define DISPLAY_CX 64
#define DISPLAY_CY 64

typedef uint16_t display_color_t;   /* RGB565, host order */

/* Palette entries are plain RGB565 so they can be scaled by intensity. */
display_color_t display_rgb(uint8_t r, uint8_t g, uint8_t b);
/* Scales a colour toward black. 0 = black, 255 = unchanged. Used for glow
 * falloff and for dimming a whole state without a second palette. */
display_color_t display_scale(display_color_t color, uint8_t intensity);

void display_clear(display_color_t color);
void display_pixel(int x, int y, display_color_t color);

/* Filled disc with a soft edge, used for the energy core. `glow` extends a
 * falloff beyond `radius`. */
void display_core(int cx, int cy, int radius, int glow, display_color_t color);

/* Ring of the given thickness. */
void display_ring(int cx, int cy, int radius, int thickness, display_color_t color);

/* Ring broken into `segments` arcs with gaps, rotated by `angle` (0-255).
 * This is the rotating element; direction comes from the sign of the angle
 * step the caller applies. */
void display_segments(int cx, int cy, int radius, int thickness, int segments,
                      int gap_percent, uint8_t angle, display_color_t color);

/* Short radial ticks around a circle, for HUD texture. */
void display_ticks(int cx, int cy, int radius, int length, int count,
                   uint8_t angle, display_color_t color);

/* Partial ring from the top, clockwise, used as the OTA progress indicator. */
void display_progress_ring(int cx, int cy, int radius, int thickness,
                           int percent, display_color_t color);

/* Symmetric level bars either side of the core, for listening and speaking. */
void display_level_bars(int cx, int cy, int level, display_color_t color);

void display_text(const char *text, int x, int y, int scale, display_color_t color);
/* Horizontally centred text; returns the x it used. */
int display_text_centered(const char *text, int y, int scale, display_color_t color);

/* Pushes the framebuffer to the panel. */
typedef void (*display_flush_fn)(const uint16_t *framebuffer);
void display_set_flush(display_flush_fn flush);
void display_present(void);

/* Allocates the framebuffer. Returns false if memory is unavailable, in which
 * case the caller must fall back to the plain text screens rather than crash. */
bool display_render_init(void);
bool display_render_ready(void);
