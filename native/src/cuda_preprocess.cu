#include "aimassist/cuda_preprocess.hpp"

#include <cuda_runtime.h>

#include <stdexcept>
#include <string>

namespace
{
__device__ __forceinline__ int clamp_coordinate(int value, int limit)
{
    return max(0, min(value, limit - 1));
}

__device__ __forceinline__ float interpolate_channel(
    std::uint8_t const* image,
    int stride,
    int x0,
    int x1,
    int y0,
    int y1,
    float tx,
    float ty,
    int channel
)
{
    auto const top_left = static_cast<float>(image[y0 * stride + x0 * 4 + channel]);
    auto const top_right = static_cast<float>(image[y0 * stride + x1 * 4 + channel]);
    auto const bottom_left = static_cast<float>(image[y1 * stride + x0 * 4 + channel]);
    auto const bottom_right = static_cast<float>(image[y1 * stride + x1 * 4 + channel]);
    auto const top = top_left + (top_right - top_left) * tx;
    auto const bottom = bottom_left + (bottom_right - bottom_left) * tx;
    return (top + (bottom - top) * ty) * (1.0F / 255.0F);
}

__global__ void bgra_to_rgb_nchw_kernel(
    std::uint8_t const* source,
    int source_width,
    int source_height,
    float* destination,
    int destination_width,
    int destination_height
)
{
    auto const pixel = blockIdx.x * blockDim.x + threadIdx.x;
    auto const pixel_count = destination_width * destination_height;
    if (pixel >= pixel_count)
    {
        return;
    }

    auto const x = pixel % destination_width;
    auto const y = pixel / destination_width;
    auto const source_x = (static_cast<float>(x) + 0.5F)
        * static_cast<float>(source_width) / static_cast<float>(destination_width) - 0.5F;
    auto const source_y = (static_cast<float>(y) + 0.5F)
        * static_cast<float>(source_height) / static_cast<float>(destination_height) - 0.5F;
    auto const floor_x = static_cast<int>(floorf(source_x));
    auto const floor_y = static_cast<int>(floorf(source_y));
    auto const x0 = clamp_coordinate(floor_x, source_width);
    auto const x1 = clamp_coordinate(floor_x + 1, source_width);
    auto const y0 = clamp_coordinate(floor_y, source_height);
    auto const y1 = clamp_coordinate(floor_y + 1, source_height);
    auto const tx = fminf(fmaxf(source_x - static_cast<float>(floor_x), 0.0F), 1.0F);
    auto const ty = fminf(fmaxf(source_y - static_cast<float>(floor_y), 0.0F), 1.0F);
    auto const source_stride = source_width * 4;
    auto const plane = destination_width * destination_height;

    destination[pixel] = interpolate_channel(
        source, source_stride, x0, x1, y0, y1, tx, ty, 2
    );
    destination[plane + pixel] = interpolate_channel(
        source, source_stride, x0, x1, y0, y1, tx, ty, 1
    );
    destination[2 * plane + pixel] = interpolate_channel(
        source, source_stride, x0, x1, y0, y1, tx, ty, 0
    );
}

void check_cuda(cudaError_t status, char const* operation)
{
    if (status != cudaSuccess)
    {
        throw std::runtime_error(
            std::string(operation) + ": " + cudaGetErrorString(status)
        );
    }
}
} // namespace

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
)
{
    if (device_bgra == nullptr || device_nchw == nullptr
        || source_width <= 0 || source_height <= 0
        || destination_width <= 0 || destination_height <= 0)
    {
        throw std::invalid_argument("Image dimensions and device buffers must be valid.");
    }

    constexpr int threads_per_block = 256;
    auto const pixel_count = destination_width * destination_height;
    auto const block_count = (pixel_count + threads_per_block - 1) / threads_per_block;
    bgra_to_rgb_nchw_kernel<<<block_count, threads_per_block, 0, stream>>>(
        device_bgra,
        source_width,
        source_height,
        device_nchw,
        destination_width,
        destination_height
    );
    check_cuda(cudaGetLastError(), "Launch CUDA image preprocessing kernel");
}
} // namespace aimassist
