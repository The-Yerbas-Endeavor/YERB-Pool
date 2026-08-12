cmake_minimum_required(VERSION 3.24)
project(YerbPoolGhostRider LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

include(FetchContent)

# Reuse the verified CPU reference implementation from The-Yerbas-Endeavor's
# Yerbas-Miner. That implementation itself pins the Yerbas Core GhostRider
# primitives, avoiding an independent pool-side reimplementation.
set(YERBAS_ENABLE_CUDA OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    yerbas_miner
    GIT_REPOSITORY https://github.com/The-Yerbas-Endeavor/Yerbas-Miner.git
    GIT_TAG 5a370203cddaa84c87e2bf2c2fb4558f5219b47b
    GIT_SHALLOW FALSE
)
FetchContent_MakeAvailable(yerbas_miner)

add_library(yerb_ghostrider SHARED bridge.cpp)
target_include_directories(yerb_ghostrider PRIVATE ${yerbas_miner_SOURCE_DIR}/src)
target_link_libraries(yerb_ghostrider PRIVATE yerbas-ghostrider-reference)
set_target_properties(yerb_ghostrider PROPERTIES OUTPUT_NAME "yerb_ghostrider")
