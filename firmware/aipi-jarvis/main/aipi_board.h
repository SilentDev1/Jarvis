#pragma once

#include "driver/gpio.h"

#define AIPI_LCD_BACKLIGHT GPIO_NUM_3
#define AIPI_AUDIO_I2C_SCL GPIO_NUM_4
#define AIPI_AUDIO_I2C_SDA GPIO_NUM_5
#define AIPI_LCD_DC GPIO_NUM_7
#define AIPI_SPEAKER_ENABLE GPIO_NUM_9
#define AIPI_LCD_CS GPIO_NUM_15
#define AIPI_LCD_SCLK GPIO_NUM_16
#define AIPI_LCD_MOSI GPIO_NUM_17
#define AIPI_LCD_RESET GPIO_NUM_18
#define AIPI_BUTTON GPIO_NUM_42

/* GPIO10 is a community-reported board power control. Never configure it. */
#define AIPI_UNVERIFIED_POWER_GPIO GPIO_NUM_10
