#pragma once

#include <stdbool.h>

#include "display_controller.h"
#include "esp_err.h"

/* Arc reactor light.
 *
 * An output abstraction, deliberately separate from the visitor and session
 * code, so no business logic ever touches a GPIO or a PWM channel directly.
 *
 * Two backends are planned. The onboard single-pixel WS2812 on GPIO46 is
 * already wired and powered by the board, so it needs no external circuitry.
 * A larger external arc-reactor light will be a second backend once the actual
 * hardware has been electrically identified; nothing here assigns a pin for it
 * or assumes anything about it.
 *
 * Disabled by default. A light at a front door that switches itself on is a
 * decision for the owner, not the firmware. */

typedef enum {
    ARC_BACKEND_NONE = 0,      /* No light. Every call is a no-op. */
    ARC_BACKEND_ONBOARD,       /* Onboard WS2812, single pixel, GPIO46. */
    /* ARC_BACKEND_EXTERNAL is intentionally absent until the physical light
     * has been identified. Adding it before then would mean guessing at a
     * voltage, a current and a pin. */
} arc_backend_t;

/* Brightness percentages are of full scale and are clamped. The defaults are
 * deliberately modest: this sits at a front door, and a WS2812 at full white
 * is both unpleasant to look at and the peak of its current draw. */
#define ARC_DEFAULT_IDLE_BRIGHTNESS 12
#define ARC_DEFAULT_ACTIVE_BRIGHTNESS 45
#define ARC_MAX_BRIGHTNESS 80
#define ARC_QUIET_SCALE_PERCENT 25

esp_err_t arc_light_init(arc_backend_t backend);
bool arc_light_available(void);

void arc_light_set_enabled(bool enabled);
bool arc_light_enabled(void);

/* Follows the same authoritative state the display uses, so the light and the
 * screen can never disagree about what Jarvis is doing. */
void arc_light_set_state(jarvis_visual_t state);

/* Reuses the envelope already computed for the display. There is no second
 * audio analysis pipeline. */
void arc_light_set_level(int level);

void arc_light_set_brightness(int idle_percent, int active_percent);
void arc_light_set_quiet(bool quiet);
void arc_light_off(void);
