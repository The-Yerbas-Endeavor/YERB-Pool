cmake_minimum_required(VERSION 3.24)
project(YerbPoolGhostRider LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

include(FetchContent)

# YERB-Pool is standalone from all miner projects. The native verifier is
# compiled directly from a pinned Yerbas Core revision so consensus hashing
# comes from the coin source itself.
FetchContent_Declare(
    yerbas_core
    GIT_REPOSITORY https://github.com/The-Yerbas-Endeavor/yerbas.git
    GIT_TAG 65c6b6336bf9cc0eb7fa125ed5aa983a17e6fe7a
    GIT_SHALLOW FALSE
)
FetchContent_GetProperties(yerbas_core)
if(NOT yerbas_core_POPULATED)
    FetchContent_Populate(yerbas_core)
endif()

set(YERBAS_CORE_SRC "${yerbas_core_SOURCE_DIR}/src")
set(YERBAS_GR_CORE_SOURCES
    ${YERBAS_CORE_SRC}/hash_selection.cpp
    ${YERBAS_CORE_SRC}/crypto/aes_helper.c
    ${YERBAS_CORE_SRC}/crypto/blake.c
    ${YERBAS_CORE_SRC}/crypto/bmw.c
    ${YERBAS_CORE_SRC}/crypto/cubehash.c
    ${YERBAS_CORE_SRC}/crypto/echo.c
    ${YERBAS_CORE_SRC}/crypto/groestl.c
    ${YERBAS_CORE_SRC}/crypto/jh.c
    ${YERBAS_CORE_SRC}/crypto/keccak.c
    ${YERBAS_CORE_SRC}/crypto/luffa.c
    ${YERBAS_CORE_SRC}/crypto/shavite.c
    ${YERBAS_CORE_SRC}/crypto/simd.c
    ${YERBAS_CORE_SRC}/crypto/skein.c
    ${YERBAS_CORE_SRC}/crypto/sph_hamsi.c
    ${YERBAS_CORE_SRC}/crypto/sph_hamsi_helper.c
    ${YERBAS_CORE_SRC}/crypto/sph_fugue.c
    ${YERBAS_CORE_SRC}/crypto/sph_shabal.c
    ${YERBAS_CORE_SRC}/crypto/sph_whirlpool.c
    ${YERBAS_CORE_SRC}/crypto/sph_sha2.c
    ${YERBAS_CORE_SRC}/crypto/sph_sha512.c
    ${YERBAS_CORE_SRC}/cryptonote/aesb.c
    ${YERBAS_CORE_SRC}/cryptonote/c_blake256.c
    ${YERBAS_CORE_SRC}/cryptonote/c_groestl.c
    ${YERBAS_CORE_SRC}/cryptonote/c_jh.c
    ${YERBAS_CORE_SRC}/cryptonote/c_keccak.c
    ${YERBAS_CORE_SRC}/cryptonote/c_skein.c
    ${YERBAS_CORE_SRC}/cryptonote/hash-ops.c
    ${YERBAS_CORE_SRC}/cryptonote/oaes_lib.c
    ${YERBAS_CORE_SRC}/cryptonote/slow-hash.c
)

foreach(source IN LISTS YERBAS_GR_CORE_SOURCES)
    if(NOT EXISTS "${source}")
        message(FATAL_ERROR "Pinned Yerbas Core GhostRider source is missing: ${source}")
    endif()
endforeach()

add_library(yerb_ghostrider SHARED
    bridge.cpp
    ghostrider_reference.cpp
    ${YERBAS_GR_CORE_SOURCES}
)

target_include_directories(yerb_ghostrider PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${YERBAS_CORE_SRC}
)

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_compile_options(yerb_ghostrider PRIVATE
        -include "${CMAKE_CURRENT_SOURCE_DIR}/glibc_endian_compat.h"
    )
endif()

set_target_properties(yerb_ghostrider PROPERTIES OUTPUT_NAME "yerb_ghostrider")
