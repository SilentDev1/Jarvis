#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "terminal_state.h"

/* The Jarvis visual interface.
 *
 * One controller, driven by the existing terminal state. It owns no state
 * machine of its own: it reads what the terminal already decided and renders
 * it, so the screen cannot disagree with the speaker or the connection.
 *
 * Rendering is best-effort. If the framebuffer cannot be allocated, or the
 * render task cannot start, the device keeps working and simply shows the
 * plain text screens. Voice, network and OTA always take priority. */

typedef enum {
    JARVIS_VISUAL_BOOT,
    JARVIS_VISUAL_CONNECTING,
    JARVIS_VISUAL_IDLE,
    JARVIS_VISUAL_VISITOR,
    JARVIS_VISUAL_LISTENING,
    JARVIS_VISUAL_PROCESSING,
    JARVIS_VISUAL_SPEAKING,
    JARVIS_VISUAL_OFFLINE,
    JARVIS_VISUAL_UPDATING,
    JARVIS_VISUAL_ERROR,
} jarvis_visual_t;

esp_err_t display_controller_start(void);

/* Sets the visual state. Cheap and safe to call from any task; the render
 * loop picks the value up on its next frame rather than drawing inline. */
void display_controller_set(jarvis_visual_t visual);
jarvis_visual_t display_controller_get(void);

/* Audio envelope, 0-100, for the reactive core. Fed from the same PCM the
 * speaker is playing, already computed, so nothing extra is calculated on the
 * audio path. */
void display_controller_set_level(int level);

/* OTA progress, shown as the outer ring filling. */
void display_controller_set_progress(int percent, const char *label);

/* One-line status under the core. NULL restores the state's default. */
void display_controller_set_status(const char *status);

/* True when the animated interface is actually running, so callers know
 * whether the plain text screens are still in use. */
bool display_controller_active(void);
