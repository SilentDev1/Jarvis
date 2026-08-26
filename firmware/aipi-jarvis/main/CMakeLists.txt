idf_component_register(
  SRCS "app_main.c" "bringup.c" "es8311_codec.c" "audio_output.c" "wifi_provision.c" "local_connection.c" "terminal_state.c" "jarvis_protocol.c" "ota_update.c"
  INCLUDE_DIRS "."
  REQUIRES app_update esp_http_client mbedtls driver esp_driver_i2c esp_driver_i2s esp_driver_spi esp_psram esp_event esp_http_server esp_netif esp_wifi json nvs_flash spi_flash espressif__esp_websocket_client
  EMBED_TXTFILES "ota_public_key.pem"
)
