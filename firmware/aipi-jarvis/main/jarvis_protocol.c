#include <string.h>
#include "jarvis_protocol.h"

jarvis_message_type_t jarvis_message_type(const char *name) {
    if (!name) return JARVIS_MESSAGE_INVALID;
    if (!strcmp(name, "PING")) return JARVIS_MESSAGE_PING;
    if (!strcmp(name, "PLAY_AUDIO_START")) return JARVIS_MESSAGE_PLAY_AUDIO_START;
    if (!strcmp(name, "PLAY_AUDIO_END")) return JARVIS_MESSAGE_PLAY_AUDIO_END;
    if (!strcmp(name, "START_LISTENING")) return JARVIS_MESSAGE_START_LISTENING;
    if (!strcmp(name, "STOP_LISTENING")) return JARVIS_MESSAGE_STOP_LISTENING;
    if (!strcmp(name, "RETURN_IDLE")) return JARVIS_MESSAGE_RETURN_IDLE;
    if (!strcmp(name, "SET_DISPLAY_STATE")) return JARVIS_MESSAGE_SET_DISPLAY_STATE;
    return JARVIS_MESSAGE_INVALID;
}
