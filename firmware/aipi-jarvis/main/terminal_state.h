#pragma once
#include <stdbool.h>

typedef enum {
    TERMINAL_BOOTING,
    TERMINAL_CONNECTING,
    TERMINAL_IDLE,
    TERMINAL_GREETING,
    TERMINAL_LISTENING,
    TERMINAL_STREAMING,
    TERMINAL_PROCESSING,
    TERMINAL_SPEAKING,
    TERMINAL_ERROR,
    TERMINAL_UPDATING,
} terminal_state_t;

const char *terminal_state_name(terminal_state_t state);
bool terminal_transition_allowed(terminal_state_t from, terminal_state_t to);
