#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <vector>

#include "hash_selection.h"
#include "uint256.h"

namespace yerbpool::ghostrider {

using Hash256 = std::array<std::uint8_t, 32>;

static uint256 previous_block_hash(const std::uint8_t* data, std::size_t size)
{
    if (data == nullptr || size < 36) throw std::invalid_argument("GhostRider input too short");
    uint256 prev;
    std::memcpy(prev.begin(), data + 4, 32);
    return prev;
}

Hash256 hash_reference(const std::uint8_t* data, std::size_t size)
{
    if (data == nullptr || size != 80) throw std::invalid_argument("GhostRider expects an 80-byte header");
    if (size > static_cast<std::size_t>(std::numeric_limits<int>::max())) throw std::invalid_argument("work buffer too large");

    HashSelection selection(
        previous_block_hash(data, size),
        {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14},
        {0,1,2,3,4,5});

    const std::vector<int> cns = selection.getCnIndexes();
    const std::vector<int> cores = selection.getAlgoIndexes();
    uint512 hash[18];

    for (int i = 0; i < 18; ++i) {
        const void* to_hash = (i == 0) ? static_cast<const void*>(data) : static_cast<const void*>(&hash[i - 1]);
        const int len = (i == 0) ? static_cast<int>(size) : 64;
        int core = -1;
        int cn = -1;

        if (i < 5) core = cores[i];
        else if (i == 5) cn = cns[0];
        else if (i < 11) core = cores[i - 1];
        else if (i == 11) cn = cns[1];
        else if (i < 17) core = cores[i - 2];
        else cn = cns[2];

        coreHash(to_hash, &hash[i], len, core);
        uint512* cn_input = (i == 0) ? &hash[0] : &hash[i - 1];
        cnHash(cn_input, &hash[i], len, cn);
    }

    const uint256 result = hash[17].trim256();
    Hash256 out{};
    std::memcpy(out.data(), result.begin(), out.size());
    return out;
}

} // namespace yerbpool::ghostrider
