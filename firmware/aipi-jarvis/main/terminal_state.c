#include <stdbool.h>
#include "terminal_state.h"

const char *terminal_state_name(terminal_state_t state) {
    static const char *names[] = {
        "BOOTING", "CONNECTING", "IDLE", "GREETING", "LISTENING",
        "STREAMING", "PROCESSING", "SPEAKING", "ERROR", "UPDATING"
    };
    return state <= TERMINAL_UPDATING ? names[state] : "ERROR";
}

bool terminal_transition_allowed(terminal_state_t from, terminal_state_t to) {
    if (to == TERMINAL_ERROR || to == TERMINAL_IDLE) return true;
    switch (from) {
        case TERMINAL_BOOTING: return to == TERMINAL_CONNECTING;
        case TERMINAL_CONNECTING: return to == TERMINAL_IDLE;
        case TERMINAL_IDLE: return to == TERMINAL_GREETING || to == TERMINAL_LISTENING || to == TERMINAL_UPDATING;
        case TERMINAL_GREETING: return to == TERMINAL_LISTENING || to == TERMINAL_SPEAKING;
        case TERMINAL_LISTENING: return to == TERMINAL_STREAMING || to == TERMINAL_PROCESSING;
        case TERMINAL_STREAMING: return to == TERMINAL_PROCESSING;
        case TERMINAL_PROCESSING: return to == TERMINAL_SPEAKING;
        case TERMINAL_SPEAKING: return to == TERMINAL_LISTENING;
        case TERMINAL_ERROR: return to == TERMINAL_CONNECTING;
        case TERMINAL_UPDATING: return false;
        default: return false;
    }
}
