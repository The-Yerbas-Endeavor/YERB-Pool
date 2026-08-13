#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace yerbpool::ghostrider {
using Hash256 = std::array<std::uint8_t, 32>;
Hash256 hash_reference(const std::uint8_t* data, std::size_t size);
}
