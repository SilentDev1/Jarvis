#pragma once

#include "driver/gpio.h"

#define AIPI_LCD_BACKLIGHT GPIO_NUM_3
#define AIPI_AUDIO_I2C_SCL GPIO_NUM_4
#define AIPI_AUDIO_I2C_SDA GPIO_NUM_5
#define AIPI_AUDIO_MCLK GPIO_NUM_6
#define AIPI_LCD_DC GPIO_NUM_7
#define AIPI_SPEAKER_ENABLE GPIO_NUM_9
#define AIPI_AUDIO_DOUT GPIO_NUM_11
#define AIPI_AUDIO_WS GPIO_NUM_12
#define AIPI_AUDIO_DIN GPIO_NUM_13
#define AIPI_AUDIO_BCLK GPIO_NUM_14
#define AIPI_LCD_CS GPIO_NUM_15
#define AIPI_LCD_SCLK GPIO_NUM_16
#define AIPI_LCD_MOSI GPIO_NUM_17
#define AIPI_LCD_RESET GPIO_NUM_18
#define AIPI_BUTTON GPIO_NUM_42
#define AIPI_WIFI_RESET_HOLD_MS 8000

/* Board power latch.
 *
 * On USB the rail is powered directly and this pin is irrelevant. On battery
 * the power button only closes the latch while it is held; firmware must drive
 * this pin high to hold the rails up, or the device dies the moment the button
 * is released. That was the observed symptom.
 *
 * Corroborated by the known-working AiPi Lite reference firmware ("GPIO10 HIGH
 * keeps rails up") and by xiaozhi-esp32, which it cites. GPIO10 is an ordinary
 * ESP32-S3 GPIO: the strapping pins are 0, 3, 45 and 46, and the flash and
 * PSRAM pins are in the 26-32 range, so driving it is safe from the MCU side. */
#define AIPI_POWER_LATCH GPIO_NUM_10
