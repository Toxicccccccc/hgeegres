#pragma once

#include "aimassist/capture_backend.hpp"
#include "aimassist/dataset.hpp"
#include "aimassist/input_provider.hpp"
#include "aimassist/latest_frame.hpp"
#include "aimassist/movement.hpp"
#include "aimassist/settings.hpp"
#include "aimassist/sigma_drift.hpp"
#include "aimassist/targeting.hpp"
#include "aimassist/tensorrt_yolo.hpp"

#include <atomic>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

#include <cuda_runtime_api.h>

namespace aimassist
{
class NativeEngine
{
public:
    explicit NativeEngine(Settings settings, std::string config_path = {});
    ~NativeEngine();

    NativeEngine(NativeEngine const&) = delete;
    NativeEngine& operator=(NativeEngine const&) = delete;

    void run(std::atomic_bool const& stop, std::optional<std::uint64_t> frame_limit = std::nullopt);

    // Description of the capture and input backends actually in use, available
    // once run() has started. The GUI shows this so the user can see which
    // backend is active rather than having to guess.
    std::string active_capture() const;
    std::string active_input() const;

private:
    // Capture thread body: publishes the newest frame into frame_slot_.
    void capture_loop(std::atomic_bool const& stop);

    // Re-read only the live-tunable preview keys from the config file while
    // running. The GUI rewrites the file when the user toggles the floating
    // preview, so polling its timestamp lets an already-running engine honour
    // that change instead of freezing the value it saw at launch.
    void refresh_live_settings();

    Settings settings_;
    TensorRtYolo model_;
    // Path of the settings file this engine was started from; empty when the
    // caller did not supply one, in which case live refresh is skipped.
    std::string config_path_;
    // Timestamp of the last settings file we read, used to skip the parse when
    // nothing changed.
    std::filesystem::file_time_type config_mtime_{};
    // Time of the last config stat(), so the mtime check is not performed on
    // every one of the hundreds of frames the loop turns over each second.
    double config_checked_at_{0.0};

    // Live capture geometry. The FOV, centres and screen size can change while
    // the engine runs (the Detection slider, the resolution dropdown). The GUI
    // writes them to the config file, refresh_live_settings() notices and sets
    // geometry_dirty_, and the capture thread re-initialises the backend for the
    // new size on its next tick. geometry_mutex_ guards the four fields so the
    // capture thread and the inference loop never read a half-updated size.
    mutable std::mutex geometry_mutex_;
    std::atomic_bool geometry_dirty_{false};
    // Largest FOV seen so far. The frame slot is only ever grown (reserve() never
    // shrinks), so it is kept at this size and never reallocated downward, which
    // would fight the in-flight capture copy.
    int frame_buffer_fov_{0};

    // Backends are created from the configured names and owned here, so the
    // capture and output mechanisms can be swapped without touching the loop.
    std::unique_ptr<ICaptureBackend> capture_;
    std::unique_ptr<IInputProvider> input_;
    std::atomic_bool capture_available_{false};
    // Set when the engine wants the capture thread to stop independently of the
    // caller's stop flag (for example once a bounded --frames run is complete).
    std::atomic_bool capture_stop_{false};
    std::string active_capture_text_;
    std::string active_input_text_;
    mutable std::mutex text_mutex_;

    // Decouples capture from inference: the capture thread overwrites the newest
    // frame, and inference always consumes the freshest one instead of a backlog.
    LatestFrameSlot frame_slot_;

    // Dedicated non-blocking stream the capture thread performs its
    // device-to-device copy on, plus the event recorded after that copy. The
    // copy used to run on the synchronising default stream, which forced it to
    // serialise against inference; now it overlaps, and the consumer waits on
    // capture_event_ before reading the buffer, so the swap-safe handoff stays
    // correct. cudaEventDisableTiming because only ordering is needed.
    cudaStream_t capture_stream_{nullptr};
    cudaEvent_t capture_event_{nullptr};
    // Recorded on the consumer's stream right after it copies the published frame
    // out of the slot. The capture thread waits on it before writing the slot
    // again, so it can never overwrite a buffer the consumer is still reading.
    // This is what makes the double-buffer swap safe with two streams.
    cudaEvent_t consume_event_{nullptr};

    // Accessibility movement shaping, applied to the tracking output.
    MovementShaper movement_;
    // SigmaDrift biomechanical movement generator (see sigma_drift.hpp).
    SigmaDrift sigma_drift_;
    TrackerState tracker_;

    // Optional labelled-data collection for later model retraining.
    DatasetCollector dataset_;

    // Resolved virtual-key codes for the lock and shoot bindings. Parsing the
    // binding strings (heap copy + lowercase + hash lookup) every frame was
    // measurable waste at these frame rates; the codes only change when the
    // settings change, so they are cached and refreshed with the live settings.
    // -1 means "not yet resolved"; 0 means a valid "no key" (used for the
    // always-on "Auto" binding, which is treated as held).
    int lock_key_vk_{-1};
    int shoot_key_vk_{-1};
    bool lock_key_auto_{false};
    bool shoot_key_auto_{false};
    std::string cached_lock_key_;
    std::string cached_shoot_key_;
};
} // namespace aimassist
