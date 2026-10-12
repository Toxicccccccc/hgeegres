#include "aimassist/capture_backend.hpp"

#include "aimassist/capture.hpp"
#include "aimassist/dxgi_capture.hpp"

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>

#include <cuda_runtime_api.h>

namespace aimassist
{
char const* to_string(CaptureKind kind) noexcept
{
    switch (kind)
    {
    case CaptureKind::DesktopDuplication:
        return "dxgi";
    case CaptureKind::Gdi:
        return "gdi";
    case CaptureKind::Synthetic:
        return "synthetic";
    }
    return "unknown";
}

CaptureKind capture_kind_from_string(std::string const& name, bool& recognized) noexcept
{
    recognized = true;
    if (name == "gdi")
    {
        return CaptureKind::Gdi;
    }
    if (name == "synthetic")
    {
        return CaptureKind::Synthetic;
    }
    if (name == "dxgi" || name == "duplication" || name.empty())
    {
        return CaptureKind::DesktopDuplication;
    }
    recognized = false;
    return CaptureKind::DesktopDuplication;
}

namespace
{
// ── Desktop Duplication (GPU resident) ────────────────────────────────────

class DuplicationBackend final : public ICaptureBackend
{
public:
    ~DuplicationBackend() override
    {
        release();
    }

    CaptureKind kind() const noexcept override
    {
        return CaptureKind::DesktopDuplication;
    }

    std::string describe() const override
    {
        if (!initialized_)
        {
            return "Desktop Duplication (not initialized)";
        }
        return std::string("Desktop Duplication + ")
            + (interop_ready_ ? "CUDA interop" : "CPU readback")
            + " (" + std::to_string(screen_width_) + "x" + std::to_string(screen_height_) + ")";
    }

    bool initialize(int fov, std::string& message) override
    {
        if (fov <= 0)
        {
            message = "FOV must be positive";
            return false;
        }

        if (!initialized_)
        {
            std::string status;
            if (!capture_.initialize(0, status))
            {
                message = status;
                return false;
            }
            screen_width_ = capture_.screen_width();
            screen_height_ = capture_.screen_height();
            initialized_ = true;
        }

        // The first capture creates the FOV-sized interop texture; subsequent
        // calls with the same FOV take the cheap path.
        CaptureStatus probe = capture(fov, 0, 0, 0);
        interop_ready_ = capture_.cuda_interop_ready();
        message = describe();
        return probe.ok;
    }

    CaptureStatus capture(int fov, int left, int top, int timeout_ms) override
    {
        CaptureStatus status;
        if (!initialized_)
        {
            status.message = "Desktop Duplication is not initialized";
            return status;
        }

        bool had_new_frame = false;
        std::string error;
        if (!capture_.capture(fov, left, top, timeout_ms, had_new_frame, error))
        {
            // A lost device or a display-mode change invalidates the duplication
            // interface; rebuild it so the next frame can succeed.
            std::string rebuild;
            initialized_ = capture_.initialize(0, rebuild);
            interop_ready_ = initialized_ && capture_.cuda_interop_ready();
            status.ok = false;
            status.message = error;
            return status;
        }

        had_new_frame_ = had_new_frame;
        if (had_new_frame && interop_ready_)
        {
            // Refresh the device-side copy the consumer reads.
            auto const bytes = static_cast<std::size_t>(fov) * static_cast<std::size_t>(fov) * 4;
            if (device_buffer_bytes_ != bytes)
            {
                if (device_buffer_ != nullptr)
                {
                    cudaFree(device_buffer_);
                    device_buffer_ = nullptr;
                }
                if (cudaMalloc(&device_buffer_, bytes) != cudaSuccess)
                {
                    device_buffer_ = nullptr;
                    status.message = "Could not allocate the capture device buffer";
                    return status;
                }
                device_buffer_bytes_ = bytes;
            }
            if (!capture_.copy_to_device(static_cast<std::uint8_t*>(device_buffer_), fov))
            {
                status.message = "Could not copy the captured frame to the device";
                return status;
            }
        }

        status.ok = true;
        status.had_new_frame = had_new_frame;
        return status;
    }

    CaptureFrame frame() const override
    {
        CaptureFrame view;
        if (interop_ready_ && device_buffer_ != nullptr)
        {
            view.device_bgra = static_cast<std::uint8_t const*>(device_buffer_);
        }
        else if (capture_.has_cpu_frame())
        {
            view.cpu_frame = &capture_.cpu_frame();
        }
        return view;
    }

    bool gpu_resident() const noexcept override
    {
        return interop_ready_;
    }

    int screen_width() const noexcept override
    {
        return screen_width_;
    }

    int screen_height() const noexcept override
    {
        return screen_height_;
    }

    void release() override
    {
        if (device_buffer_ != nullptr)
        {
            cudaFree(device_buffer_);
            device_buffer_ = nullptr;
        }
        device_buffer_bytes_ = 0;
        capture_.release();
        initialized_ = false;
        interop_ready_ = false;
    }

private:
    DxgiDesktopCapture capture_;
    void* device_buffer_{};
    std::size_t device_buffer_bytes_{};
    bool initialized_{};
    bool interop_ready_{};
    bool had_new_frame_{};
    int screen_width_{};
    int screen_height_{};
};

// ── GDI (CPU) ─────────────────────────────────────────────────────────────

class GdiBackend final : public ICaptureBackend
{
public:
    ~GdiBackend() override
    {
        release();
    }

    CaptureKind kind() const noexcept override
    {
        return CaptureKind::Gdi;
    }

    std::string describe() const override
    {
        return "GDI BitBlt (CPU)";
    }

    bool initialize(int fov, std::string& message) override
    {
        if (fov <= 0)
        {
            message = "FOV must be positive";
            return false;
        }
        // GDI has no separate init step; the first capture creates the DIB.
        screen_width_ = GetSystemMetrics(SM_CXSCREEN);
        screen_height_ = GetSystemMetrics(SM_CYSCREEN);
        message = describe();
        return true;
    }

    CaptureStatus capture(int fov, int left, int top, int timeout_ms) override
    {
        (void)timeout_ms;
        CaptureStatus status;
        try
        {
            frame_ = &capture_.capture(fov, left, top);
            status.ok = true;
            // GDI always returns the current desktop, so a frame is always new.
            status.had_new_frame = true;
        }
        catch (std::exception const& error)
        {
            status.message = error.what();
        }
        return status;
    }

    CaptureFrame frame() const override
    {
        CaptureFrame view;
        if (frame_ != nullptr)
        {
            view.cpu_frame = frame_;
        }
        return view;
    }

    bool gpu_resident() const noexcept override
    {
        return false;
    }

    int screen_width() const noexcept override
    {
        return screen_width_;
    }

    int screen_height() const noexcept override
    {
        return screen_height_;
    }

    void release() override
    {
        capture_.release();
        frame_ = nullptr;
    }

private:
    DesktopCapture capture_;
    std::vector<std::uint8_t> const* frame_{};
    int screen_width_{};
    int screen_height_{};
};

// ── Synthetic (testing) ──────────────────────────────────────────────────

// Produces a deterministic moving pattern. This lets the full pipeline --
// preprocessing, inference, decoding, tracking, telemetry -- run in automated
// tests with no desktop, no game, and identical input on every machine.
class SyntheticBackend final : public ICaptureBackend
{
public:
    CaptureKind kind() const noexcept override
    {
        return CaptureKind::Synthetic;
    }

    std::string describe() const override
    {
        return "Synthetic moving pattern (test source)";
    }

    bool initialize(int fov, std::string& message) override
    {
        if (fov <= 0)
        {
            message = "FOV must be positive";
            return false;
        }
        fov_ = fov;
        buffer_.assign(
            static_cast<std::size_t>(fov) * static_cast<std::size_t>(fov) * 4,
            0
        );
        message = describe();
        return true;
    }

    CaptureStatus capture(int fov, int left, int top, int timeout_ms) override
    {
        (void)left;
        (void)top;
        (void)timeout_ms;
        CaptureStatus status;
        if (fov <= 0 || fov != fov_)
        {
            std::string message;
            if (!initialize(fov, message))
            {
                status.message = message;
                return status;
            }
        }

        ++frame_index_;
        // A drifting gradient with a bright moving square gives the detector
        // structured, non-degenerate input and changes between frames.
        auto const square_x = (frame_index_ * 3) % std::max(1, fov_ - 40);
        auto const square_y = (frame_index_ * 2) % std::max(1, fov_ - 40);
        for (int y = 0; y < fov_; ++y)
        {
            for (int x = 0; x < fov_; ++x)
            {
                auto const index = (static_cast<std::size_t>(y) * fov_ + x) * 4;
                auto const inside = x >= square_x && x < square_x + 40
                    && y >= square_y && y < square_y + 40;
                auto const value = inside
                    ? static_cast<std::uint8_t>(240)
                    : static_cast<std::uint8_t>((x + y + frame_index_) % 256);
                buffer_[index + 0] = inside ? 60 : value;
                buffer_[index + 1] = value;
                buffer_[index + 2] = inside ? 60 : value;
                buffer_[index + 3] = 255;
            }
        }

        status.ok = true;
        status.had_new_frame = true;
        return status;
    }

    CaptureFrame frame() const override
    {
        CaptureFrame view;
        view.cpu_frame = &buffer_;
        return view;
    }

    bool gpu_resident() const noexcept override
    {
        return false;
    }

    int screen_width() const noexcept override
    {
        return fov_;
    }

    int screen_height() const noexcept override
    {
        return fov_;
    }

    void release() override
    {
        buffer_.clear();
    }

private:
    int fov_{};
    std::uint64_t frame_index_{};
    std::vector<std::uint8_t> buffer_;
};
} // namespace

ICaptureBackend* create_capture_backend(CaptureKind kind)
{
    switch (kind)
    {
    case CaptureKind::DesktopDuplication:
        return new DuplicationBackend();
    case CaptureKind::Gdi:
        return new GdiBackend();
    case CaptureKind::Synthetic:
        return new SyntheticBackend();
    }
    return nullptr;
}
} // namespace aimassist
