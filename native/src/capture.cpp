#include "aimassist/capture.hpp"

#include <Windows.h>

#include <cstring>
#include <stdexcept>
#include <string>

namespace
{
void throw_last_error(char const* operation)
{
    throw std::runtime_error(
        std::string(operation) + " failed with Windows error " + std::to_string(GetLastError())
    );
}
} // namespace

namespace aimassist
{
DesktopCapture::~DesktopCapture()
{
    release();
}

void DesktopCapture::release()
{
    auto* memory_dc = static_cast<HDC>(memory_dc_);
    auto* previous_bitmap = static_cast<HGDIOBJ>(previous_bitmap_);
    auto* bitmap = static_cast<HBITMAP>(bitmap_);
    auto* window_dc = static_cast<HDC>(window_dc_);
    auto* hwnd = static_cast<HWND>(hwnd_);

    if (memory_dc != nullptr && previous_bitmap != nullptr)
    {
        SelectObject(memory_dc, previous_bitmap);
    }
    if (bitmap != nullptr)
    {
        DeleteObject(bitmap);
    }
    if (memory_dc != nullptr)
    {
        DeleteDC(memory_dc);
    }
    if (hwnd != nullptr && window_dc != nullptr)
    {
        ReleaseDC(hwnd, window_dc);
    }

    hwnd_ = nullptr;
    window_dc_ = nullptr;
    memory_dc_ = nullptr;
    bitmap_ = nullptr;
    previous_bitmap_ = nullptr;
    bits_ = nullptr;
    size_ = 0;
}

void DesktopCapture::ensure_resources(int fov)
{
    if (size_ == fov && bitmap_ != nullptr)
    {
        return;
    }
    release();

    auto* hwnd = GetDesktopWindow();
    auto* window_dc = GetWindowDC(hwnd);
    if (window_dc == nullptr)
    {
        throw_last_error("GetWindowDC");
    }
    auto* memory_dc = CreateCompatibleDC(window_dc);
    if (memory_dc == nullptr)
    {
        ReleaseDC(hwnd, window_dc);
        throw_last_error("CreateCompatibleDC");
    }

    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = fov;
    info.bmiHeader.biHeight = -fov;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;

    void* bits = nullptr;
    auto* bitmap = CreateDIBSection(memory_dc, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (bitmap == nullptr || bits == nullptr)
    {
        DeleteDC(memory_dc);
        ReleaseDC(hwnd, window_dc);
        throw_last_error("CreateDIBSection");
    }
    auto* previous = SelectObject(memory_dc, bitmap);
    hwnd_ = hwnd;
    window_dc_ = window_dc;
    memory_dc_ = memory_dc;
    bitmap_ = bitmap;
    previous_bitmap_ = previous;
    bits_ = bits;
    size_ = fov;
}

std::vector<std::uint8_t> const& DesktopCapture::capture(int fov, int left, int top)
{
    try
    {
        ensure_resources(fov);
        auto* memory_dc = static_cast<HDC>(memory_dc_);
        auto* window_dc = static_cast<HDC>(window_dc_);
        if (!BitBlt(memory_dc, 0, 0, fov, fov, window_dc, left, top, SRCCOPY))
        {
            throw_last_error("BitBlt");
        }
        GdiFlush();
        auto const bytes = static_cast<std::size_t>(fov) * static_cast<std::size_t>(fov) * 4;
        frame_.resize(bytes);
        std::memcpy(frame_.data(), bits_, bytes);
        return frame_;
    }
    catch (...)
    {
        release();
        throw;
    }
}
} // namespace aimassist
