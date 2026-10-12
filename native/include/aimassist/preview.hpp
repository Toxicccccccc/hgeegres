#pragma once

// Live preview streaming from the native engine to the GUI control panel.
//
// The engine keeps every captured frame on the GPU; the GUI only ever needs a
// small picture of what the detector sees. Copying full frames over the pipe
// would waste the very latency this project fights for, so the preview path:
//   * pulls the FOV crop back to the host at a fixed, low cadence (default
//     20 previews per second, decoupled from the inference rate);
//   * nearest-neighbour downsamples it on the CPU to a small square;
//   * emits one "PREVIEW" line: width, height, then the BGR bytes in base64.
// Detection boxes are NOT baked into the image. The Python bridge draws them,
// which keeps this side free of any drawing code and lets the GUI restyle the
// overlay without touching the engine.
//
// The cadence is deliberately lower than the detection rate: at 800 fps of
// detection a 20 fps preview is already four times faster than the eye needs,
// and it costs a few hundred kilobytes per second instead of saturating stdout.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace aimassist
{
    inline char const *const base64_alphabet =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    inline void append_base64(std::string &out, std::uint8_t const *data, std::size_t size)
    {
        out.reserve(out.size() + (size + 2) / 3 * 4);
        std::size_t i = 0;
        for (; i + 3 <= size; i += 3)
        {
            std::uint32_t const triple =
                (static_cast<std::uint32_t>(data[i]) << 16) | (static_cast<std::uint32_t>(data[i + 1]) << 8) | static_cast<std::uint32_t>(data[i + 2]);
            out.push_back(base64_alphabet[(triple >> 18) & 0x3F]);
            out.push_back(base64_alphabet[(triple >> 12) & 0x3F]);
            out.push_back(base64_alphabet[(triple >> 6) & 0x3F]);
            out.push_back(base64_alphabet[triple & 0x3F]);
        }
        if (i < size)
        {
            std::uint32_t const triple = static_cast<std::uint32_t>(data[i]) << 16 | (i + 1 < size ? static_cast<std::uint32_t>(data[i + 1]) << 8 : 0);
            out.push_back(base64_alphabet[(triple >> 18) & 0x3F]);
            out.push_back(base64_alphabet[(triple >> 12) & 0x3F]);
            out.push_back(i + 1 < size ? base64_alphabet[(triple >> 6) & 0x3F] : '=');
            out.push_back('=');
        }
    }

    // Append a float with minimal characters (no trailing zeros), for the
    // compact box list carried after the preview image. Plain "%g"-style output
    // keeps the line short without pulling in a formatted-stream dependency.
    inline void append_number(std::string &out, float value)
    {
        if (!std::isfinite(value))
        {
            out += '0';
            return;
        }
        char buffer[32];
        auto const written = std::snprintf(buffer, sizeof(buffer), "%g", static_cast<double>(value));
        if (written > 0)
        {
            out.append(buffer, static_cast<std::size_t>(written));
        }
    }

    // Downsample a BGRA frame to a small BGRA square by nearest-neighbour
    // sampling. Nearest keeps the inner loop branch-free and is visually fine at
    // preview scale; area averaging would cost four reads per pixel for no gain
    // a 240px floating window can show.
    inline void downsample_bgra(
        std::uint8_t const *source,
        int source_size,
        int target_size,
        std::vector<std::uint8_t> &destination)
    {
        destination.resize(static_cast<std::size_t>(target_size) * target_size * 4);
        double const ratio = static_cast<double>(source_size) / target_size;
        for (int y = 0; y < target_size; ++y)
        {
            auto const source_y = static_cast<int>(std::min(
                static_cast<double>(y) * ratio, source_size - 1.0));
            auto const source_row = source + static_cast<std::size_t>(source_y) * source_size * 4;
            auto destination_row = destination.data() + static_cast<std::size_t>(y) * target_size * 4;
            for (int x = 0; x < target_size; ++x)
            {
                auto const source_x = static_cast<int>(std::min(
                    static_cast<double>(x) * ratio, source_size - 1.0));
                std::memcpy(destination_row + x * 4, source_row + source_x * 4, 4);
            }
        }
    }

    // BGRA -> tightly packed BGR, in place of the alpha channel.
    inline void bgra_to_bgr(std::vector<std::uint8_t> const &bgra, std::vector<std::uint8_t> &bgr)
    {
        bgr.resize(bgra.size() / 4 * 3);
        for (std::size_t pixel = 0; pixel < bgra.size() / 4; ++pixel)
        {
            bgr[pixel * 3 + 0] = bgra[pixel * 4 + 0];
            bgr[pixel * 3 + 1] = bgra[pixel * 4 + 1];
            bgr[pixel * 3 + 2] = bgra[pixel * 4 + 2];
        }
    }
} // namespace aimassist
