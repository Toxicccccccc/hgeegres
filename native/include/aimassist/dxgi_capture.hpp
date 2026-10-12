#pragma once

// GPU screen capture via the DXGI Desktop Duplication API.
//
// Adapted from the approach used by both reference projects
// (sunone_aimbot_2 capture/duplication_api_capture.cpp and Redock's
// dxgi_capture.h). Desktop Duplication hands us a GPU texture containing the
// desktop, so the FOV crop can be copied GPU-to-GPU with CopySubresourceRegion
// and consumed directly by CUDA -- no render-to-CPU-then-upload round trip.
//
// Two consumption paths are supported:
//   * capture_to_device():  D3D11 texture -> registered CUDA array (interop).
//     This is the fast path and keeps the frame on the GPU end to end.
//   * capture_to_cpu():     D3D11 texture -> staging texture -> system memory.
//     Used as a fallback if CUDA interop cannot be set up, so the engine still
//     runs on machines where the interop registration fails.
//
// Desktop Duplication only produces a new frame when something on screen
// changes. A timeout therefore means "no update", and callers should re-use the
// previous frame rather than treating it as an error -- this is what lets the
// loop run faster than the desktop refresh without wasted copies.

#include <cstdint>
#include <string>
#include <vector>

namespace aimassist
{
class DxgiDesktopCapture
{
public:
    DxgiDesktopCapture() = default;
    ~DxgiDesktopCapture();

    DxgiDesktopCapture(DxgiDesktopCapture const&) = delete;
    DxgiDesktopCapture& operator=(DxgiDesktopCapture const&) = delete;

    // Create the D3D11 device and duplication interface for a monitor.
    // `monitor_index` selects the output (0 = first). Returns false and fills
    // `status` on failure; callers fall back to the GDI capture in that case.
    bool initialize(int monitor_index, std::string& status);

    // Register the FOV-sized interop texture with CUDA. Safe to call before the
    // first capture; on failure the CPU path remains available.
    bool enable_cuda_interop(std::string& status);
    bool cuda_interop_ready() const noexcept;

    // Grab the next desktop frame, cropped to the FOV rectangle.
    // Returns true when a new frame was produced. When `timeout_ms` elapses
    // with no change, returns false and `had_new_frame` reports whether the
    // previous frame is still valid for re-use.
    bool capture(int fov, int left, int top, int timeout_ms, bool& had_new_frame, std::string& status);

    // Copy the most recent GPU frame into a caller-owned linear device buffer,
    // as tightly packed BGRA rows. This is the fast path: the frame never
    // visits system memory. Returns false when CUDA interop is unavailable, in
    // which case the caller should use cpu_frame().
    bool copy_to_device(std::uint8_t* device_destination, int fov);

    // Host copy of the cropped BGRA frame. Only populated on the CPU path.
    std::vector<std::uint8_t> const& cpu_frame() const noexcept;
    bool has_cpu_frame() const noexcept;

    bool initialized() const noexcept;
    int screen_width() const noexcept;
    int screen_height() const noexcept;

    void release();

private:
    bool create_staging_texture(int fov);
    bool create_interop_texture(int fov);
    void release_resources();
    bool acquire_frame(bool& had_new_frame, std::string& status);

    void* device_{};
    void* context_{};
    void* duplication_{};
    void* output1_{};
    void* staging_texture_{};
    void* interop_texture_{};
    void* cuda_interop_{};

    bool frame_acquired_{};
    bool has_cpu_frame_{};

    int monitor_index_{};
    int screen_width_{};
    int screen_height_{};
    int region_size_{};
    int region_left_{};
    int region_top_{};

    std::vector<std::uint8_t> cpu_frame_;
};
} // namespace aimassist
