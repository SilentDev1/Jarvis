idf_component_register(
  SRCS "app_main.c" "terminal_state.c" "jarvis_protocol.c"
  INCLUDE_DIRS "."
  REQUIRES esp_event esp_netif nvs_flash
)
