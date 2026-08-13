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
    SOURCE_SUBDIR __yerbpool_no_subdir__
)
FetchContent_MakeAvailable(yerbas_core)

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

# Yerbas Core normally gets these HAVE_DECL_* values from its Autoconf-generated
# configuration header. YERB-Pool compiles only the GhostRider sources directly,
# so provide the declarations explicitly on Linux where glibc already supplies
# these endian helpers. Without these definitions compat/endian.h treats every
# helper as missing and redefines htole*/htobe*/le*toh/be*toh under GCC 15.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_compile_definitions(yerb_ghostrider PRIVATE
        HAVE_ENDIAN_H=1
        HAVE_DECL_HTOBE16=1
        HAVE_DECL_HTOLE16=1
        HAVE_DECL_BE16TOH=1
        HAVE_DECL_LE16TOH=1
        HAVE_DECL_HTOBE32=1
        HAVE_DECL_HTOLE32=1
        HAVE_DECL_BE32TOH=1
        HAVE_DECL_LE32TOH=1
        HAVE_DECL_HTOBE64=1
        HAVE_DECL_HTOLE64=1
        HAVE_DECL_BE64TOH=1
        HAVE_DECL_LE64TOH=1
    )
endif()

set_target_properties(yerb_ghostrider PROPERTIES OUTPUT_NAME "yerb_ghostrider")
