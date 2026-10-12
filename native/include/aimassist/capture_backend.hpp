#pragma once

// Modular screen-capture layer.
//
// Several capture backends exist because no single one is best everywhere:
// Desktop Duplication is the fastest on Windows 8+ and keeps frames on the GPU,
// while GDI works on older setups and in unusual desktop configurations (some
// remote-desktop sessions, exclusive fullscreen fallbacks). Rather than
// committing to one, the engine selects a backend by name and reports which one
// is active and why.
//
// All backends use documented, public Windows and graphics APIs. None of them
// touch the game process, inject code, or install drivers.
//
// A backend is expected to be cheap after initialization: resources are created
// once and reused, never per frame.

#include <cstdint>
#include <string>
#include <vector>

namespace aimassist
{
    // Identifies a capture implementation in configuration and telemetry.
    enum class CaptureKind
    {
        // DXGI Desktop Duplication + CUDA/D3D11 interop (GPU resident).
        DesktopDuplication,
        // GDI BitBlt into a reused DIB section (CPU).
        Gdi,
        // Deterministic moving pattern, no screen access. Used by tests so the
        // pipeline can be exercised without a desktop or a game.
        Synthetic,
    };

    char const *to_string(CaptureKind kind) noexcept;

    // Resolves a configuration string ("dxgi", "gdi", "synthetic") to a backend.
    // Unknown names resolve to the default and set `recognized` to false so callers
    // can report a typo instead of silently changing behavior.
    CaptureKind capture_kind_from_string(std::string const &name, bool &recognized) noexcept;

    // A frame handed to the consumer. Depending on the backend and whether CUDA
    // interop is available, exactly one of the two views is valid:
    //  * `device_bgra` is non-null when the frame already lives in GPU memory and
    //    the buffer is a tightly packed FOV x FOV BGRA image written by the backend.
    //  * `cpu_frame` is used when the backend produced host pixels.
    struct CaptureFrame
    {
        std::uint8_t const *device_bgra{};
        std::vector<std::uint8_t> const *cpu_frame{};
    };

    struct CaptureStatus
    {
        bool ok{};
        bool had_new_frame{};
        std::string message;
    };

    // Backend contract. Implementations own their resources and must release them
    // deterministically in release()/the destructor.
    class ICaptureBackend
    {
    public:
        virtual ~ICaptureBackend() = default;

        virtual CaptureKind kind() const noexcept = 0;

        // Human-readable description of the active configuration, for the GUI and
        // for the startup log. Available after initialize() succeeds.
        virtual std::string describe() const = 0;

        // Prepare resources for an FOV of the given size. Must be idempotent for a
        // repeated identical size and must handle a size change by rebuilding only
        // what depends on the size.
        virtual bool initialize(int fov, std::string &message) = 0;

        // Acquire the next frame cropped to the FOV centred on `left`/`top`.
        // Returns a status whose `had_new_frame` is false when the desktop has not
        // changed, in which case the previously returned frame remains valid.
        virtual CaptureStatus capture(int fov, int left, int top, int timeout_ms) = 0;

        // The most recent frame, valid until the next capture() call.
        virtual CaptureFrame frame() const = 0;

        // Whether this backend can supply `device_bgra`.
        virtual bool gpu_resident() const noexcept = 0;

        // Screen size, discovered during initialize(). Zero when unknown.
        virtual int screen_width() const noexcept = 0;
        virtual int screen_height() const noexcept = 0;

        virtual void release() = 0;
    };

    // Creates a backend instance. The caller owns the returned pointer.
    // Returns nullptr for an unknown kind.
    ICaptureBackend *create_capture_backend(CaptureKind kind);
} // namespace aimassist
