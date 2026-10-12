#pragma once

#include <cstdint>
#include <vector>

namespace aimassist
{
class DesktopCapture
{
public:
    DesktopCapture() = default;
    ~DesktopCapture();

    DesktopCapture(DesktopCapture const&) = delete;
    DesktopCapture& operator=(DesktopCapture const&) = delete;

    std::vector<std::uint8_t> const& capture(int fov, int left, int top);
    void release();

private:
    void ensure_resources(int fov);

    void* hwnd_{};
    void* window_dc_{};
    void* memory_dc_{};
    void* bitmap_{};
    void* previous_bitmap_{};
    void* bits_{};
    int size_{};
    std::vector<std::uint8_t> frame_;
};
} // namespace aimassist
