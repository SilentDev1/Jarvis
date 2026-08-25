idf_component_register(
  SRCS "app_main.c" "bringup.c" "wifi_provision.c" "terminal_state.c" "jarvis_protocol.c"
  INCLUDE_DIRS "."
  REQUIRES driver esp_driver_i2c esp_driver_spi esp_psram esp_event esp_http_server esp_netif esp_wifi nvs_flash spi_flash
)
