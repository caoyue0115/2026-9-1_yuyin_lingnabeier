#include "board_audio.h"

#include "config.h"

#include <assert.h>
#include <stdbool.h>

#include "bsp/esp_vocat.h"
#include "esp_check.h"
#include "esp_codec_dev_defaults.h"
#include "esp_err.h"
#include "esp_log.h"

static const char *TAG = "board_audio";

#define BOARD_AUDIO_I2S_GPIO_CFG       \
    {                                  \
        .mclk = BSP_I2S_MCLK,          \
        .bclk = BSP_I2S_SCLK,          \
        .ws = BSP_I2S_LCLK,            \
        .dout = BSP_I2S_DOUT,          \
        .din = DEMO_AUDIO_I2S_DIN_GPIO,\
        .invert_flags = {              \
            .mclk_inv = false,         \
            .bclk_inv = false,         \
            .ws_inv = false,           \
        },                             \
    }

#define BOARD_AUDIO_I2S_DUPLEX_CFG(_sample_rate)                                                     \
    {                                                                                                 \
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(_sample_rate),                                          \
        .slot_cfg = I2S_STD_PHILIP_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO), \
        .gpio_cfg = BOARD_AUDIO_I2S_GPIO_CFG,                                                         \
    }

static i2s_chan_handle_t s_i2s_tx_chan = NULL;
static i2s_chan_handle_t s_i2s_rx_chan = NULL;
static const audio_codec_data_if_t *s_i2s_data_if = NULL;

static bool board_audio_error_is_ok(esp_err_t ret, const char *operation)
{
    if (ret == ESP_OK) {
        return true;
    }
    ESP_LOGE(TAG, "%s failed: %s", operation, esp_err_to_name(ret));
    return false;
}

esp_err_t board_audio_init(const i2s_std_config_t *i2s_config)
{
    esp_err_t ret = ESP_FAIL;
    if (s_i2s_tx_chan != NULL && s_i2s_rx_chan != NULL) {
        return ESP_OK;
    }

    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(CONFIG_BSP_I2S_NUM, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;
    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan_cfg, &s_i2s_tx_chan, &s_i2s_rx_chan),
                        TAG,
                        "I2S channel allocation failed");

    const i2s_std_config_t std_cfg_default = BOARD_AUDIO_I2S_DUPLEX_CFG(48000);
    const i2s_std_config_t *p_i2s_cfg = i2s_config != NULL ? i2s_config : &std_cfg_default;
    if (s_i2s_tx_chan != NULL) {
        ESP_GOTO_ON_ERROR(i2s_channel_init_std_mode(s_i2s_tx_chan, p_i2s_cfg), err, TAG, "I2S tx init failed");
        ESP_GOTO_ON_ERROR(i2s_channel_enable(s_i2s_tx_chan), err, TAG, "I2S tx enable failed");
    }
    if (s_i2s_rx_chan != NULL) {
        ESP_GOTO_ON_ERROR(i2s_channel_init_std_mode(s_i2s_rx_chan, p_i2s_cfg), err, TAG, "I2S rx init failed");
        ESP_GOTO_ON_ERROR(i2s_channel_enable(s_i2s_rx_chan), err, TAG, "I2S rx enable failed");
    }

    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = CONFIG_BSP_I2S_NUM,
        .rx_handle = s_i2s_rx_chan,
        .tx_handle = s_i2s_tx_chan,
    };
    s_i2s_data_if = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_GOTO_ON_FALSE(s_i2s_data_if != NULL, ESP_ERR_NO_MEM, err, TAG, "I2S codec data interface allocation failed");

    ESP_LOGI(TAG,
             "audio_board_init audio_pcb_rev=%s audio_i2s_din_gpio=%d audio_pa_gpio=%d audio_gpio48_enable=%d",
             DEMO_BOARD_AUDIO_PCB_REVISION,
             (int)DEMO_AUDIO_I2S_DIN_GPIO,
             (int)DEMO_AUDIO_PA_GPIO,
             DEMO_AUDIO_GPIO48_ENABLE);
    return ESP_OK;

err:
    if (s_i2s_tx_chan != NULL) {
        i2s_del_channel(s_i2s_tx_chan);
        s_i2s_tx_chan = NULL;
    }
    if (s_i2s_rx_chan != NULL) {
        i2s_del_channel(s_i2s_rx_chan);
        s_i2s_rx_chan = NULL;
    }
    s_i2s_data_if = NULL;
    return ret;
}

static const audio_codec_data_if_t *board_audio_get_codec_itf(void)
{
    return s_i2s_data_if;
}

esp_codec_dev_handle_t board_audio_codec_speaker_init(void)
{
    const audio_codec_data_if_t *i2s_data_if = board_audio_get_codec_itf();
    if (i2s_data_if == NULL) {
        if (!board_audio_error_is_ok(bsp_i2c_init(), "bsp_i2c_init")) {
            return NULL;
        }
        if (!board_audio_error_is_ok(board_audio_init(NULL), "board_audio_init")) {
            return NULL;
        }
        i2s_data_if = board_audio_get_codec_itf();
    }
    assert(i2s_data_if);

#if DEMO_AUDIO_GPIO48_ENABLE
    if (!board_audio_error_is_ok(bsp_feature_enable(BSP_FEATURE_SPEAKER, true), "speaker feature enable")) {
        return NULL;
    }
#else
    ESP_LOGI(TAG, "skip speaker GPIO48 enable: audio_gpio48_enable=0");
#endif

    const audio_codec_gpio_if_t *gpio_if = audio_codec_new_gpio();

    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = BSP_I2C_NUM,
        .addr = ES8311_CODEC_DEFAULT_ADDR,
        .bus_handle = bsp_i2c_get_handle(),
    };
    const audio_codec_ctrl_if_t *i2c_ctrl_if = audio_codec_new_i2c_ctrl(&i2c_cfg);
    if (i2c_ctrl_if == NULL) {
        ESP_LOGE(TAG, "speaker I2C control allocation failed");
        return NULL;
    }

    esp_codec_dev_hw_gain_t gain = {
        .pa_voltage = 5.0,
        .codec_dac_voltage = 3.3,
    };

    es8311_codec_cfg_t codec_cfg = {
        .ctrl_if = i2c_ctrl_if,
        .gpio_if = gpio_if,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .pa_pin = DEMO_AUDIO_PA_GPIO,
        .pa_reverted = false,
        .master_mode = false,
        .hw_gain = gain,
    };
    const audio_codec_if_t *dev = es8311_codec_new(&codec_cfg);
    if (dev == NULL) {
        ESP_LOGE(TAG, "speaker codec allocation failed");
        return NULL;
    }

    esp_codec_dev_cfg_t codec_dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT,
        .codec_if = dev,
        .data_if = i2s_data_if,
    };
    return esp_codec_dev_new(&codec_dev_cfg);
}

esp_codec_dev_handle_t board_audio_codec_microphone_init(void)
{
    const audio_codec_data_if_t *i2s_data_if = board_audio_get_codec_itf();
    if (i2s_data_if == NULL) {
        if (!board_audio_error_is_ok(bsp_i2c_init(), "bsp_i2c_init")) {
            return NULL;
        }
        if (!board_audio_error_is_ok(board_audio_init(NULL), "board_audio_init")) {
            return NULL;
        }
        i2s_data_if = board_audio_get_codec_itf();
    }
    assert(i2s_data_if);

#if DEMO_AUDIO_GPIO48_ENABLE
    if (!board_audio_error_is_ok(bsp_feature_enable(BSP_FEATURE_MIC, true), "microphone feature enable")) {
        return NULL;
    }
#else
    ESP_LOGI(TAG, "skip microphone GPIO48 enable: audio_gpio48_enable=0");
#endif

    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = BSP_I2C_NUM,
        .addr = ES7210_CODEC_DEFAULT_ADDR,
        .bus_handle = bsp_i2c_get_handle(),
    };
    const audio_codec_ctrl_if_t *i2c_ctrl_if = audio_codec_new_i2c_ctrl(&i2c_cfg);
    if (i2c_ctrl_if == NULL) {
        ESP_LOGE(TAG, "microphone I2C control allocation failed");
        return NULL;
    }

    es7210_codec_cfg_t codec_cfg = {
        .ctrl_if = i2c_ctrl_if,
    };
    const audio_codec_if_t *dev = es7210_codec_new(&codec_cfg);
    if (dev == NULL) {
        ESP_LOGE(TAG, "microphone codec allocation failed");
        return NULL;
    }

    esp_codec_dev_cfg_t codec_dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN,
        .codec_if = dev,
        .data_if = i2s_data_if,
    };
    return esp_codec_dev_new(&codec_dev_cfg);
}
