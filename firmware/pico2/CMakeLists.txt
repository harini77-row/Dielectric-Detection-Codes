cmake_minimum_required(VERSION 3.13)

# Pico 2: rp2350 Arm cores
set(PICO_BOARD pico2 CACHE STRING "Board")
set(PICO_PLATFORM rp2350-arm-s CACHE STRING "Platform")

include(pico_sdk_import.cmake)
project(pgdd_trusted C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(pgdd_trusted
    src/main.c
    src/record.c
    src/adf4351.c
    src/ads1115.c
    src/ds18b20.c
    src/cradle.c
    src/commit_gate.c
    src/host_link.c
)
target_include_directories(pgdd_trusted PRIVATE include src)
pico_generate_pio_header(pgdd_trusted ${CMAKE_CURRENT_LIST_DIR}/src/consistency.pio)

target_link_libraries(pgdd_trusted
    pico_stdlib pico_rand
    hardware_spi hardware_i2c hardware_pio hardware_dma hardware_sync)

target_compile_options(pgdd_trusted PRIVATE -Wall -Wextra -Wno-unused-parameter)

# Debug console on UART0 (GP0/GP1). USB stdio off: the USB port is not a data path.
pico_enable_stdio_uart(pgdd_trusted 1)
pico_enable_stdio_usb(pgdd_trusted 0)
pico_add_extra_outputs(pgdd_trusted)
