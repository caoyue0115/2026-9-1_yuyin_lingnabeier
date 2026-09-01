cmake_minimum_required(VERSION 3.16)

# Reuse the ESP-VoCat N16R8 profile validated on the existing devices.
# Controlled OTA/canary builds may still override SDKCONFIG_DEFAULTS.
if(NOT DEFINED SDKCONFIG_DEFAULTS)
    set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.defaults.vocat_lowcost_16m8m")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp_idf_demo)
