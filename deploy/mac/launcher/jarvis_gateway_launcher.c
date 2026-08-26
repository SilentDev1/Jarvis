/*
 * Minimal launcher for the Jarvis local device gateway.
 *
 * Why this exists: on macOS, a launchd job that lives under a TCC-protected
 * directory (~/Documents, ~/Desktop, ~/Downloads) cannot read its own
 * repository. TCC attributes a shell script's access to the *interpreter*, so
 * making the agent work by granting access to the script would really mean
 * granting Full Disk Access to /bin/sh, and therefore to every shell script on
 * the machine.
 *
 * This binary exists so the owner can grant that access to one purpose-built
 * executable instead. It does exactly one thing: exec the gateway supervisor
 * at the compile-time path. It takes no arguments, reads no configuration, and
 * runs nothing else, so the granted access cannot be repurposed.
 */
#include <stdio.h>
#include <unistd.h>

#ifndef JARVIS_GATEWAY_SCRIPT
#error "JARVIS_GATEWAY_SCRIPT must be defined at compile time"
#endif

int main(void) {
    char *const argv[] = {"/bin/sh", JARVIS_GATEWAY_SCRIPT, NULL};
    execv("/bin/sh", argv);
    perror("jarvis-gateway-launcher: execv");
    return 127;
}
