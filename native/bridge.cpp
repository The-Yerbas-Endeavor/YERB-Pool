#include <cstddef>
#include <cstdint>
#include <cstring>

#include "ghostrider/ghostrider.h"

#if defined(_WIN32)
#define YERB_EXPORT extern "C" __declspec(dllexport)
#else
#define YERB_EXPORT extern "C" __attribute__((visibility("default")))
#endif

YERB_EXPORT int yerb_ghostrider_hash(const std::uint8_t* data,
                                     std::size_t size,
                                     std::uint8_t* out32)
{
    if (data == nullptr || out32 == nullptr || size != 80) return 1;
    try {
        const yerbas::ghostrider::Work work{data, size};
        const auto hash = yerbas::ghostrider::hash_reference(work);
        std::memcpy(out32, hash.data(), hash.size());
        return 0;
    } catch (...) {
        return 2;
    }
}
