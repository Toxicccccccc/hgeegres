#pragma once

#include <cuda_runtime_api.h>

#include <cstdint>

namespace aimassist
{
void launch_bgra_to_rgb_nchw(
    std::uint8_t const* device_bgra,
    int source_width,
    int source_height,
    float* device_nchw,
    int destination_width,
    int destination_height,
    cudaStream_t stream
);
} // namespace aimassist
