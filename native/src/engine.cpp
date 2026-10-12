#include "aimassist/engine.hpp"

#include "aimassist/input.hpp"
#include "aimassist/preview.hpp"
#include "aimassist/sigma_drift.hpp"
#include "aimassist/telemetry.hpp"

#include <Windows.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace
{
double now_seconds()
{
    using clock = std::chrono::steady_clock;
    return std::chrono::duration<double>(clock::now().time_since_epoch()).count();
}

std::string utc_timestamp()
{
    auto const now = std::chrono::system_clock::now();
    auto const time = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
    gmtime_s(&utc, &time);
    auto const milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()
    ).count() % 1000;
    std::ostringstream stream;
    stream << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.'
           << std::setw(3) << std::setfill('0') << milliseconds << "+00:00";
    return stream.str();
}

std::string telemetry_path()
{
    auto const logs = std::filesystem::current_path() / "logs";
    std::filesystem::create_directories(logs);
    auto const now = std::chrono::system_clock::now();
    auto const time = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
    gmtime_s(&utc, &time);
    auto const microseconds = std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()
    ).count() % 1000000;
    std::ostringstream name;
    name << "pipeline_metrics_" << std::put_time(&utc, "%Y%m%dT%H%M%S")
         << std::setw(6) << std::setfill('0') << microseconds << "Z.csv";
    return (logs / name.str()).string();
}

void set_below_normal_priority()
{
    // Run the engine a notch BELOW the game so it can never cause a scheduling
    // stall in the game itself. The engine is latency-tolerant (a frame a few
    // milliseconds late is invisible), whereas a starved game drops frames the
    // player sees. Below normal keeps the assist responsive while guaranteeing
    // the game always wins the CPU. Done in-process, so it holds no matter who
    // launched the engine (start.bat, the GUI, or a manual run).
    if (!SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
    {
        std::cerr << "Could not set process priority to Below Normal\n";
    }
    else
    {
        std::cout << "Native process priority set to Below Normal\n";
    }
}
} // namespace

namespace aimassist
{
NativeEngine::NativeEngine(Settings settings, std::string config_path)
    : settings_(std::move(settings)),
      model_(settings_.model_path),
      config_path_(std::move(config_path))
{
    if (settings_.model_path.empty())
    {
        throw std::invalid_argument("Settings must include a TensorRT .engine model_path.");
    }
    if (!config_path_.empty())
    {
        std::error_code error;
        config_mtime_ = std::filesystem::last_write_time(config_path_, error);
    }

    // A dedicated, non-blocking stream for the capture thread's device-to-device
    // copy and an event that marks that copy complete. Previously the copy ran on
    // the synchronising default stream, so it could not overlap any inference
    // work; now it runs concurrently and the consumer waits on the event instead,
    // which keeps the double-buffered handoff correct while removing the stall.
    if (cudaStreamCreateWithFlags(&capture_stream_, cudaStreamNonBlocking) != cudaSuccess)
    {
        capture_stream_ = nullptr;
        std::cerr << "Could not create the capture CUDA stream; capture copy will be serialised\n";
    }
    if (cudaEventCreateWithFlags(&capture_event_, cudaEventDisableTiming) != cudaSuccess)
    {
        capture_event_ = nullptr;
    }
    if (cudaEventCreateWithFlags(&consume_event_, cudaEventDisableTiming) != cudaSuccess)
    {
        consume_event_ = nullptr;
    }
}

NativeEngine::~NativeEngine()
{
    // The stream and event are only ever used on the capture and inference
    // threads, both of which have joined by the time run() returns or the object
    // is destroyed on an error path. Destroying them here releases the CUDA
    // resources without relying on process teardown.
    if (consume_event_ != nullptr)
    {
        cudaEventDestroy(consume_event_);
        consume_event_ = nullptr;
    }
    if (capture_event_ != nullptr)
    {
        cudaEventDestroy(capture_event_);
        capture_event_ = nullptr;
    }
    if (capture_stream_ != nullptr)
    {
        cudaStreamDestroy(capture_stream_);
        capture_stream_ = nullptr;
    }
}

void NativeEngine::refresh_live_settings()
{
    // The GUI rewrites its config file whenever a setting changes, including the
    // floating-preview toggle. Re-reading just the preview keys here means a
    // running session starts (or stops) streaming the moment the user ticks the
    // box, instead of keeping the value it saw at launch. Only the preview keys
    // are applied: capture geometry, model, and serial settings still require a
    // restart because they cannot be swapped mid-run.
    if (config_path_.empty())
    {
        return;
    }
    // Throttle the stat() to a few times a second. The loop runs at hundreds of
    // frames per second and a preview toggle is a human action, so polling more
    // often than this is pure overhead.
    auto const now = now_seconds();
    if (now - config_checked_at_ < 0.25)
    {
        return;
    }
    config_checked_at_ = now;
    std::error_code error;
    auto const current = std::filesystem::last_write_time(config_path_, error);
    if (error || current == config_mtime_)
    {
        return;
    }
    config_mtime_ = current;
    try
    {
        auto const fresh = load_settings(config_path_);
        settings_.preview_stream_enabled = fresh.preview_stream_enabled;
        settings_.preview_fps = fresh.preview_fps;
        settings_.preview_size = fresh.preview_size;
        // The lock/shoot bindings are safe to swap live: they only change how the
        // next iteration reads the keys, never capture or inference geometry.
        // Without this a lock key recorded in the GUI after the engine started
        // would appear to do nothing until a restart.
        settings_.lock_key = fresh.lock_key;
        settings_.shoot_input = fresh.shoot_input;
        // Detection-rate cap is safe to change mid-run: it only paces the loop.
        settings_.detection_fps_limit = fresh.detection_fps_limit;
        // Movement feel is safe to swap live too: it only affects how the next
        // step is shaped, never the capture or inference geometry. When the
        // method actually changes, abort any in-flight SigmaDrift plan so a
        // half-finished trajectory does not bleed into the legacy path.
        if (settings_.movement_method != fresh.movement_method)
        {
            sigma_drift_.stop();
        }
        settings_.movement_method = fresh.movement_method;
        settings_.movement_smoothing_enabled = fresh.movement_smoothing_enabled;
        settings_.movement_max_step_px = fresh.movement_max_step_px;
        settings_.movement_acceleration = fresh.movement_acceleration;
        settings_.movement_stop_tolerance_px = fresh.movement_stop_tolerance_px;
        MovementSettings live_movement;
        live_movement.enabled = settings_.movement_smoothing_enabled;
        live_movement.max_step_px = settings_.movement_max_step_px;
        live_movement.acceleration = settings_.movement_acceleration;
        live_movement.stop_tolerance_px = settings_.movement_stop_tolerance_px;
        movement_.set_settings(live_movement);

        // SigmaDrift tuning and recoil compensation affect only how the next
        // stroke is generated, so they are safe to change live. Snap takes effect
        // on the next acquisition; any in-flight stroke is left to finish so a
        // mid-stroke change cannot produce a discontinuous jump.
        settings_.sigmadrift_snap = fresh.sigmadrift_snap;
        settings_.sigmadrift_target_width = fresh.sigmadrift_target_width;
        settings_.sigmadrift_curvature_scale = fresh.sigmadrift_curvature_scale;
        settings_.sigmadrift_overshoot_prob = fresh.sigmadrift_overshoot_prob;
        settings_.sigmadrift_ou_sigma = fresh.sigmadrift_ou_sigma;
        settings_.sigmadrift_tremor_amp_max = fresh.sigmadrift_tremor_amp_max;
        settings_.sigmadrift_sdn_k = fresh.sigmadrift_sdn_k;
        settings_.sigmadrift_sample_dt_mean = fresh.sigmadrift_sample_dt_mean;
        settings_.recoil_compensation = fresh.recoil_compensation;
        settings_.recoil_strength = fresh.recoil_strength;
        // Hard lock is safe to toggle live: it only changes how the next stroke is
        // generated. Any in-flight trajectory is dropped so the switch to rigid
        // tracking takes effect immediately.
        if (fresh.hard_lock != settings_.hard_lock)
        {
            sigma_drift_.stop();
        }
        settings_.hard_lock = fresh.hard_lock;
        {
            auto sigma_live = sigma_drift_.config();
            sigma_live.target_width = static_cast<double>(settings_.sigmadrift_target_width);
            sigma_live.curvature_scale = static_cast<double>(settings_.sigmadrift_curvature_scale);
            sigma_live.overshoot_prob = static_cast<double>(settings_.sigmadrift_overshoot_prob);
            sigma_live.ou_sigma = static_cast<double>(settings_.sigmadrift_ou_sigma);
            sigma_live.tremor_amp_max = static_cast<double>(settings_.sigmadrift_tremor_amp_max);
            sigma_live.sdn_k = static_cast<double>(settings_.sigmadrift_sdn_k);
            sigma_live.sample_dt_mean = static_cast<double>(settings_.sigmadrift_sample_dt_mean);
            sigma_live.snap = static_cast<double>(settings_.sigmadrift_snap) / 100.0;
            sigma_live.direct = settings_.hard_lock;
            sigma_drift_.set_config(sigma_live);
        }

        // Live capture geometry. The Detection slider and the resolution
        // dropdown both write these keys, and the user expects the search area
        // to track them immediately rather than on the next restart. Only the
        // four geometry fields are compared; everything else above is either
        // free to change or is read fresh each iteration. The capture thread owns
        // applying the new size, so this only flags the change.
        bool geometry_changed = false;
        {
            std::lock_guard<std::mutex> lock(geometry_mutex_);
            if (fresh.fov != settings_.fov
                || fresh.offset_x != settings_.offset_x
                || fresh.offset_y != settings_.offset_y
                || fresh.width != settings_.width
                || fresh.height != settings_.height)
            {
                settings_.fov = fresh.fov;
                settings_.offset_x = fresh.offset_x;
                settings_.offset_y = fresh.offset_y;
                settings_.width = fresh.width;
                settings_.height = fresh.height;
                geometry_changed = true;
            }
        }
        if (geometry_changed)
        {
            geometry_dirty_.store(true);
        }
    }
    catch (std::exception const&)
    {
        // A transient half-written file (defensive: the GUI writes atomically)
        // is not fatal; keep the current values and try again next frame.
    }
}

void NativeEngine::run(std::atomic_bool const& stop, std::optional<std::uint64_t> frame_limit)
{
    // SigmaDrift is planned in aim-error space; these remember the error the
    // in-flight stroke was planned for so a target that moves mid-stroke triggers
    // a fresh plan instead of the aim freezing until the old one expires.
    float planned_error_x_ = 0.0F;
    float planned_error_y_ = 0.0F;
    constexpr float reacquire_plan_radius = 12.0F;
    set_below_normal_priority();
    std::cout << "Loading native engine: " << settings_.model_path << '\n';
    std::cout << "TensorRT input " << model_.input_width() << 'x' << model_.input_height()
              << ", classes=" << model_.class_count() << '\n';

    // The engine is compiled for one fixed square input and every captured frame
    // is resized to it. If that size is much larger than the capture FOV the
    // model is inferring on upscaled pixels -- no extra detail, but ~(size/FOV)^2
    // more compute and postprocess work every frame. Point the user at the fix
    // (re-export with --imgsz equal to the FOV rounded up to a multiple of 32)
    // instead of leaving the waste silent.
    {
        auto const engine_size = std::max(model_.input_width(), model_.input_height());
        auto const fov = settings_.fov;
        if (fov > 0 && engine_size > fov + fov / 8)
        {
            auto const ideal = ((fov + 31) / 32) * 32;
            std::cout << "NOTE: engine input " << engine_size << "px is larger than the "
                      << fov << "px FOV; frames are upscaled with no gain.\n"
                      << "      Re-export the model with --imgsz " << ideal
                      << " to cut inference and NMS cost.\n";
        }
    }

    // Select capture and input backends from configuration. An unrecognized
    // name is reported and the default is used, rather than silently changing
    // behavior.
    bool capture_recognized = true;
    auto const capture_kind = capture_kind_from_string(settings_.capture_backend, capture_recognized);
    if (!capture_recognized)
    {
        std::cerr << "Unknown capture_backend '" << settings_.capture_backend
                  << "'; using '" << to_string(capture_kind) << "'.\n";
    }
    capture_.reset(create_capture_backend(capture_kind));
    if (capture_ == nullptr)
    {
        throw std::runtime_error("Could not create the configured capture backend.");
    }

    std::string capture_status;
    if (!capture_->initialize(settings_.fov, capture_status))
    {
        // Fall back to GDI, which works almost everywhere, and say so plainly.
        std::cerr << "Capture backend '" << to_string(capture_kind) << "' failed: "
                  << capture_status << "\n";
        if (capture_kind != CaptureKind::Gdi)
        {
            std::cout << "Capture: falling back to GDI\n";
            capture_.reset(create_capture_backend(CaptureKind::Gdi));
            if (capture_ == nullptr || !capture_->initialize(settings_.fov, capture_status))
            {
                throw std::runtime_error("No usable capture backend: " + capture_status);
            }
        }
        else
        {
            throw std::runtime_error("Capture backend failed: " + capture_status);
        }
    }
    {
        std::lock_guard<std::mutex> lock(text_mutex_);
        active_capture_text_ = capture_->describe();
    }
    std::cout << "Capture: " << capture_->describe() << "\n";

    bool input_recognized = true;
    auto const input_kind = input_kind_from_string(settings_.input_backend, input_recognized);
    if (!input_recognized)
    {
        std::cerr << "Unknown input_backend '" << settings_.input_backend
                  << "'; using '" << to_string(input_kind) << "'.\n";
    }
    input_ = create_input_provider(input_kind);
    if (input_ == nullptr)
    {
        throw std::runtime_error("Could not create the configured input provider.");
    }
    std::string input_status;
    if (!input_->connect(settings_.port, input_status))
    {
        std::cerr << input_status << '\n';
    }
    else
    {
        std::cout << input_status << '\n';
    }
    {
        std::lock_guard<std::mutex> lock(text_mutex_);
        active_input_text_ = input_->describe();
    }

    // Accessibility movement shaping, configured from the shared settings.
    MovementSettings movement_settings;
    movement_settings.enabled = settings_.movement_smoothing_enabled;
    movement_settings.max_step_px = settings_.movement_max_step_px;
    movement_settings.acceleration = settings_.movement_acceleration;
    movement_settings.stop_tolerance_px = settings_.movement_stop_tolerance_px;
    movement_.set_settings(movement_settings);

    // SigmaDrift biomechanical movement generator. When enabled it replaces the
    // accessibility shaper's trajectory with a biomechanically-grounded one
    // (sigma-lognormal strokes, OU drift, tremor, signal-dependent noise). The
    // config is populated from the loaded settings: it used to be a fresh default
    // that ignored every sigmadrift_* key, so tuning them in the GUI had no
    // effect on the .engine path and SigmaDrift always ran at its (slow) defaults.
    SigmaDriftConfig sigma_config;
    sigma_config.target_width = static_cast<double>(settings_.sigmadrift_target_width);
    sigma_config.curvature_scale = static_cast<double>(settings_.sigmadrift_curvature_scale);
    sigma_config.overshoot_prob = static_cast<double>(settings_.sigmadrift_overshoot_prob);
    sigma_config.ou_sigma = static_cast<double>(settings_.sigmadrift_ou_sigma);
    sigma_config.tremor_amp_max = static_cast<double>(settings_.sigmadrift_tremor_amp_max);
    sigma_config.sdn_k = static_cast<double>(settings_.sigmadrift_sdn_k);
    sigma_config.sample_dt_mean = static_cast<double>(settings_.sigmadrift_sample_dt_mean);
    // Snap (0-100) is the day-to-day control: it scales the movement time and the
    // biomechanical noise so a lock closes fast and lands cleanly.
    sigma_config.snap = static_cast<double>(settings_.sigmadrift_snap) / 100.0;
    // Hard lock skips the generative trajectory entirely: the whole correction is
    // emitted in one step, which is the lowest possible latency to the target.
    sigma_config.direct = settings_.hard_lock;
    sigma_drift_.set_config(sigma_config);
    // Movement method is re-read live (see refresh_live_settings), so this is a
    // helper rather than a captured constant: switching to "legacy" must take
    // effect immediately, not on the next restart.
    auto use_sigma_drift = [this]() {
        return settings_.movement_method != "legacy";
    };
    std::cout << "Movement: "
              << (use_sigma_drift() ? "SigmaDrift" : "legacy")
              << (settings_.movement_smoothing_enabled ? " (shaper on)" : " (shaper off)") << '\n';

    DatasetSettings dataset_settings;
    dataset_settings.enabled = settings_.dataset_enabled;
    dataset_settings.save_frames = settings_.dataset_save_frames;
    dataset_settings.min_confidence = settings_.dataset_min_confidence;
    dataset_settings.max_frames_per_second = settings_.dataset_max_frames_per_second;
    dataset_settings.output_dir = settings_.dataset_dir;
    dataset_settings.class_names = settings_.dataset_class_names;
    if (dataset_settings.enabled)
    {
        std::string dataset_status;
        if (dataset_.start(dataset_settings, dataset_status))
        {
            std::cout << dataset_status << '\n';
        }
        else
        {
            std::cerr << "Dataset collection unavailable: " << dataset_status << '\n';
        }
    }

    // CSV telemetry is opt-in. When it is off no file is opened at all, which is
    // the default: the loop is uncapped and a per-frame log is a diagnostics
    // tool, not something a normal session should pay disk and I/O for.
    TelemetryWriter telemetry(settings_.telemetry_csv_enabled ? telemetry_path() : std::string{});
    if (settings_.telemetry_csv_enabled)
    {
        if (telemetry.ok())
        {
            std::cout << "Pipeline telemetry: " << telemetry.path() << '\n';
        }
        else
        {
            std::cerr << "Could not create pipeline telemetry file\n";
        }
    }

    // Idle back-off: after this many consecutive frames with no target, hold the
    // configured idle frame rate instead of spinning at full speed.
    constexpr int idle_grace_frames = 45;
    int idle_frames = 0;
    std::cout << "Idle back-off: "
              << (settings_.idle_backoff_enabled ? "enabled" : "disabled")
              << " floor " << settings_.idle_fps_floor << " fps"
              << ", pipeline CSV telemetry "
              << (settings_.telemetry_csv_enabled ? "on" : "off") << '\n';

    std::uint64_t sequence = 0;
    auto const model_name = std::filesystem::path(settings_.model_path).filename().string();
    auto const infer_confidence = std::min(settings_.confidence_threshold, 0.25F);

    // Live preview to the GUI: a fixed-cadence host copy of the FOV crop,
    // downsampled and streamed as base64. Detection runs on the GPU; the only
    // host cost is one small frame every preview_fps, not per inference.
    double last_preview_at = 0.0;
    double loop_step_ms = 7.8;
    // Recomputed each iteration so a live preview_fps change takes effect; the
    // GUI can rewrite it while the engine runs.
    auto preview_interval = [this]() {
        return 1.0 / static_cast<double>(std::max(settings_.preview_fps, 1));
    };
    std::vector<std::uint8_t> preview_small;
    std::vector<std::uint8_t> preview_bgr;
    // Reused host staging buffer for the FOV pull. Allocating a fresh fov*fov*4
    // vector on every preview forced the allocator to hand back (and zero-in) a
    // megabyte each time; keeping it across previews removes that churn from the
    // loop.
    std::vector<std::uint8_t> preview_full;
    std::string preview_line;

    // Capture runs on its own thread and publishes the newest frame. Inference
    // never waits on a queue: it takes whatever is current, so a slow frame
    // costs freshness instead of building latency.
    auto const frame_bytes = static_cast<std::size_t>(settings_.fov)
        * static_cast<std::size_t>(settings_.fov) * 4;
    if (!frame_slot_.reserve(frame_bytes))
    {
        throw std::runtime_error("Could not allocate the capture frame slot on the GPU.");
    }
    capture_stop_.store(false);
    std::thread capture_thread(&NativeEngine::capture_loop, this, std::cref(stop));

    while (!stop.load())
    {
        auto const frame_started = now_seconds();
        // Pick up a live preview toggle (and preview fps/size) before deciding
        // whether to stream this iteration.
        refresh_live_settings();
        try
        {
            // Every iteration either performs a full inference or counts as a
            // no-frame tick, so the frame limit always terminates the loop even
            // while capture is still warming up.
            if (!capture_available_.load() || !frame_slot_.has_frame())
            {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                if (frame_limit.has_value() && sequence >= *frame_limit)
                {
                    break;
                }
                continue;
            }

            // Read the live geometry under the lock so a concurrent FOV change
            // (from the Detection slider) is applied atomically here.
            int live_fov;
            {
                std::lock_guard<std::mutex> lock(geometry_mutex_);
                live_fov = settings_.fov;
            }
            auto const live_frame_bytes = static_cast<std::size_t>(live_fov)
                * static_cast<std::size_t>(live_fov) * 4;
            // The slot is only ever grown, so a larger FOV is safe to request here
            // and a smaller one reuses the existing buffer.
            frame_slot_.reserve(live_frame_bytes);

            // Consume the freshest published frame into the model's device
            // buffer. This is a device-to-device copy, so nothing reaches the
            // host except the detection tensor itself.
            //
            // The capture thread filled the slot on capture_stream_ and published
            // immediately, so the copy may still be in flight. Make this thread's
            // default stream wait on the capture event before copying out of the
            // slot: the wait is a no-op when the copy already finished (the common
            // case), and otherwise it is exactly the ordering the double buffer
            // needs. No host synchronisation is introduced.
            if (capture_event_ != nullptr)
            {
                cudaStreamWaitEvent(nullptr, capture_event_, 0);
            }
            auto const capture_started = now_seconds();
            auto* device_frame = model_.device_frame_buffer(live_fov, live_fov);
            if (device_frame == nullptr
                || !frame_slot_.copy_latest_into(device_frame, live_frame_bytes))
            {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            // Mark the published buffer as fully consumed, so the capture thread
            // knows it may overwrite it, and wait for that copy to complete.
            //
            // The wait closes a cross-stream hazard: copy_latest_into() runs on
            // the default stream, but infer_device() copies the frame onward on
            // its own non-blocking stream, with no implicit ordering between the
            // two. Synchronising the consume event here guarantees device_frame
            // is fully written before inference reads it. It costs nothing in
            // practice because infer_device() already blocks on its stream
            // (cudaStreamSynchronize) a few lines later for the TensorRT output.
            if (consume_event_ != nullptr)
            {
                cudaEventRecord(consume_event_, nullptr);
                cudaEventSynchronize(consume_event_);
            }
            auto const capture_completed = now_seconds();
            auto const timestamp = utc_timestamp();
            loop_step_ms = std::max(1.0, (capture_completed - capture_started) * 1000.0);

            // Resolve and poll the lock key before inference so the optional
            // inference gate can avoid a model call while the player is idle.
            if (settings_.lock_key != cached_lock_key_)
            {
                cached_lock_key_ = settings_.lock_key;
                lock_key_auto_ = settings_.lock_key == "Auto";
                lock_key_vk_ = lock_key_auto_ ? 0 : resolve_input_key(settings_.lock_key);
            }
            auto const lock_active = lock_key_auto_ || input_is_pressed_vk(lock_key_vk_);
            bool const inference_paused = settings_.inference_only_when_aiming && !lock_active;
            InferenceResult inference;
            if (!inference_paused)
            {
                inference = model_.infer_device(
                    device_frame,
                    live_fov,
                    live_fov,
                    infer_confidence,
                    // NMS overlap must come from the user's IoU threshold, not a
                    // hard-coded value: the schema slider had no effect on the native
                    // path, so overlapping boxes were suppressed at a fixed 0.7 while
                    // the user was told a different number was in force.
                    std::clamp(settings_.iou_threshold, 0.0F, 1.0F),
                    std::max(100, settings_.detection_limit)
                );
            }
            auto const predict_completed = now_seconds();
            auto const decode_completed = now_seconds();

            // Poll shoot fresh each frame; lock was already polled before inference.
            if (settings_.shoot_input != cached_shoot_key_)
            {
                cached_shoot_key_ = settings_.shoot_input;
                shoot_key_auto_ = settings_.shoot_input == "Auto";
                shoot_key_vk_ = shoot_key_auto_ ? 0 : resolve_input_key(settings_.shoot_input);
            }
            // The lock key is a plain hold: the assist is active only while the
            // player keeps the bound key or mouse button down. That is the right
            // feel for a button that shares the same input the player aims with.
            auto const shoot_active = shoot_key_auto_ || input_is_pressed_vk(shoot_key_vk_);
            auto command = process_detections(
                inference.detections,
                settings_,
                tracker_,
                lock_active,
                shoot_active,
                now_seconds()
            );
            if (inference_paused)
            {
                command.status = "Waiting for Lock input; inference paused";
            }
            auto const planned_move_x = command.move_x;
            auto const planned_move_y = command.move_y;

            // Movement generation. "sigmadrift" (the default) plans a whole
            // biomechanical trajectory per acquisition; "legacy" runs the desired
            // correction through the accessibility shaper (bound the step, ease it
            // in and out, settle cleanly). The two are alternatives, applied here
            // so they affect output but never the detection or tracking decision.
            if (command.send)
            {
                if (settings_.hard_lock)
                {
                    // Hard lock: process_detections already produced the exact
                    // correction to put the crosshair on the target this frame.
                    // Neither the trajectory generator nor the accessibility
                    // shaper may touch it -- any ramp or step cap here would
                    // re-introduce the very lag the mode exists to remove. The
                    // generators are reset so a later switch to a normal mode
                    // starts clean.
                    movement_.reset();
                    sigma_drift_.stop();
                }
                else if (use_sigma_drift())
                {
                    // SigmaDrift owns the trajectory: the plan contains the
                    // ballistic stroke and the corrective sub-movements, so the
                    // legacy step is never added on top (that would double the
                    // intended distance and break the bell-shaped profile).
                    //
                    // The plan is expressed in *aim-error space*: it runs from the
                    // current accumulated correction (0) to the remaining error
                    // (command.move_x/move_y). step() reports how far along that
                    // plan the stroke has travelled, and the per-frame delta it
                    // returns is the correction to send. Planning from the running
                    // absolute position instead (as this used to) reset the target
                    // to "wherever the crosshair is plus this frame's error" every
                    // step, so the stroke never converged and the random drift was
                    // re-seeded constantly -- the aim wandered and SigmaDrift
                    // looked like it "did nothing".
                    float const error_x = static_cast<float>(command.move_x);
                    float const error_y = static_cast<float>(command.move_y);
                    auto const error_magnitude = std::sqrt(error_x * error_x + error_y * error_y);
                    // Re-plan when the plan is finished, or when the live error has
                    // moved on from the one the plan was built for. Without the
                    // second check a plan that has reached its endpoint but is
                    // still "active" (it ticks out a few zero steps before it
                    // self-terminates) would ignore a target that has since moved,
                    // so the crosshair would freeze off the head until the old plan
                    // expired. SigmaDrift is planned in error space, so a materially
                    // different error means the old stroke is stale.
                    bool const plan_stale =
                        std::abs(error_x - planned_error_x_) + std::abs(error_y - planned_error_y_)
                        > reacquire_plan_radius;
                    if ((!sigma_drift_.active() || plan_stale) && error_magnitude >= 1.0F)
                    {
                        // Fresh acquisition (or the target moved): plan the whole
                        // stroke from the current correction to the remaining error.
                        sigma_drift_.begin_move(0.0F, 0.0F, error_x, error_y);
                        planned_error_x_ = error_x;
                        planned_error_y_ = error_y;
                    }
                    int drift_x = 0, drift_y = 0;
                    sigma_drift_.step(loop_step_ms, drift_x, drift_y);
                    // SigmaDrift owns the whole trajectory, so its step is the
                    // output. It is only bounded by the per-frame cap, never run
                    // through the accessibility shaper: that shaper is a *separate*
                    // movement generator with its own acceleration state, and
                    // feeding a bell-shaped SigmaDrift step into it re-shaped the
                    // profile, zeroed small real steps inside its stop tolerance,
                    // and let its "settling" flag cancel the stroke mid-flight.
                    // The two are alternatives, not layers.
                    auto const cap = movement_.settings().max_step_px;
                    command.move_x = static_cast<int>(std::clamp(
                        static_cast<float>(drift_x), -cap, cap));
                    command.move_y = static_cast<int>(std::clamp(
                        static_cast<float>(drift_y), -cap, cap));
                    // Keep the shaper's momentum at zero so switching back to the
                    // legacy path starts clean rather than resuming stale velocity.
                    movement_.reset();
                }
                else
                {
                    auto const shaped = movement_.shape(
                        static_cast<float>(command.move_x),
                        static_cast<float>(command.move_y)
                    );
                    command.move_x = shaped.step_x;
                    command.move_y = shaped.step_y;
                    if (shaped.settling && !command.click)
                    {
                        // Already on target with nothing to do this frame.
                        command.send = false;
                    }
                }
            }
            else
            {
                // Lock released or no target: stop immediately and drop
                // momentum so the aim does not drift after the player lets go.
                movement_.reset();
                sigma_drift_.stop();
            }
            auto const processing_completed = now_seconds();

            int sent_move_x = 0;
            int sent_move_y = 0;
            if (command.send && input_ != nullptr && input_->connected())
            {
                if (input_->send(command.move_x, command.move_y, command.click))
                {
                    sent_move_x = command.move_x;
                    sent_move_y = command.move_y;
                }
                else
                {
                    std::cerr << "Input provider failed; releasing buttons.\n";
                    input_->release_buttons();
                }
            }
            // The tracker computed its next error using the planned command.
            // Movement shaping and SigmaDrift can change that command, and an
            // unavailable input provider can suppress it entirely. Reconcile
            // against the movement actually delivered so the next held-lock frame
            // continues closing the real remaining gap.
            tracker_.applied_offset_x += static_cast<float>(sent_move_x - planned_move_x);
            tracker_.applied_offset_y += static_cast<float>(sent_move_y - planned_move_y);
            if (use_sigma_drift() && lock_active && command.has_target)
            {
                // Keep SigmaDrift's stale-plan reference in the same error space
                // as the crosshair: ordinary progress toward the target is not
                // new target motion and must not restart the trajectory each frame.
                planned_error_x_ -= static_cast<float>(sent_move_x);
                planned_error_y_ -= static_cast<float>(sent_move_y);
            }

            // Stream a preview frame to the GUI at the configured cadence. The
            // copy happens here, after inference, so the frame already in the
            // model's device buffer is what the GUI sees -- the exact pixels
            // that were just searched -- not a slightly newer capture.
            auto const preview_now = now_seconds();
            if (settings_.preview_stream_enabled
                && preview_now - last_preview_at >= preview_interval())
            {
                last_preview_at = preview_now;
                auto* device_bgra = model_.device_frame_buffer(live_fov, live_fov);
                if (device_bgra != nullptr)
                {
                    preview_small.clear();
                    preview_bgr.clear();
                    preview_line.clear();
                    // Pull only the downsampled target straight to the host:
                    // one 240x240x4 copy per preview, never the full FOV.
                    auto const full_bytes = static_cast<std::size_t>(live_fov)
                        * static_cast<std::size_t>(live_fov) * 4;
                    preview_full.resize(full_bytes);
                    if (cudaMemcpy(
                            preview_full.data(), device_bgra, full_bytes,
                            cudaMemcpyDeviceToHost) == cudaSuccess)
                    {
                        downsample_bgra(
                            preview_full.data(), live_fov, settings_.preview_size,
                            preview_small);
                        bgra_to_bgr(preview_small, preview_bgr);
                        preview_line.reserve(
                            32 + preview_bgr.size() / 3 * 4);
                        preview_line += "PREVIEW "
                            + std::to_string(settings_.preview_size) + " "
                            + std::to_string(settings_.preview_size) + " ";
                        append_base64(preview_line, preview_bgr.data(), preview_bgr.size());
                        // Append the detection boxes so the GUI can draw them on
                        // the preview. The coordinates are scaled into the SAME
                        // pixel space as the streamed image (preview_size), not the
                        // raw FOV, so the GUI draws them 1:1 on whatever size it
                        // renders the frame at. Emitting raw FOV coordinates meant
                        // the consumer had to re-derive the FOV from its own
                        // settings, and any disagreement (a live FOV change, a
                        // clamped preview size) drew the boxes at the wrong scale --
                        // the reported "zooming" of the detection boxes. Format,
                        // after the base64 (which contains no spaces):
                        //   " x1,y1,x2,y2,conf,class;..."  (nothing when none)
                        auto const preview_scale = settings_.preview_size > 0
                            ? static_cast<float>(settings_.preview_size)
                                / static_cast<float>(std::max(live_fov, 1))
                            : 1.0F;
                        for (auto const& detection : inference.detections)
                        {
                            preview_line += ' ';
                            append_number(preview_line, detection.x1 * preview_scale);
                            preview_line += ',';
                            append_number(preview_line, detection.y1 * preview_scale);
                            preview_line += ',';
                            append_number(preview_line, detection.x2 * preview_scale);
                            preview_line += ',';
                            append_number(preview_line, detection.y2 * preview_scale);
                            preview_line += ',';
                            append_number(preview_line, detection.confidence);
                            preview_line += ',';
                            preview_line += std::to_string(detection.class_id);
                            preview_line += ';';
                        }
                        std::cout << preview_line << '\n';
                    }
                }
            }

            // Offer the frame and its detections to the dataset collector when
            // enabled. This is non-blocking: the collector queues and drops.
            if (dataset_.active())
            {
                dataset_.submit(
                    device_frame,
                    settings_.fov,
                    inference.detections,
                    sequence + 1
                );
            }

            ++sequence;
            FrameTimings timings;
            timings.capture_ms = (capture_completed - capture_started) * 1000.0;
            timings.prepare_ms = inference.timings.upload_preprocess_ms;
            timings.predict_ms = inference.timings.predict_ms;
            timings.result_transfer_decode_ms = inference.timings.result_copy_ms
                + (decode_completed - predict_completed) * 1000.0;
            timings.postprocess_ms = (processing_completed - decode_completed) * 1000.0;
            timings.preview_ms = 0.0;
            timings.capture_to_detection_ms = (processing_completed - capture_started) * 1000.0;
            timings.capture_to_preview_ms = timings.capture_to_detection_ms;
            if (settings_.telemetry_csv_enabled)
            {
                telemetry.write(timestamp, sequence, model_name, "cuda:0", timings);
                if (sequence % 60 == 0)
                {
                    telemetry.flush();
                }
            }

            // Hold the idle frame rate when nothing has been seen for a while, so
            // an empty screen (desktop, menu, no game running) costs a fraction of
            // the GPU time. The first accepted target resets this immediately.
            if (command.has_target)
            {
                idle_frames = 0;
            }
            else
            {
                ++idle_frames;
            }
            if (settings_.idle_backoff_enabled
                && idle_frames > idle_grace_frames
                && settings_.idle_fps_floor > 0)
            {
                auto const target_interval = std::chrono::duration<double>(
                    1.0 / static_cast<double>(settings_.idle_fps_floor));
                auto const spent = std::chrono::duration<double>(processing_completed - frame_started);
                if (spent < target_interval)
                {
                    std::this_thread::sleep_for(target_interval - spent);
                }
            }

            // Optional detection-rate cap. Zero (the default) means unlimited:
            // the loop runs as fast as capture and inference allow, which is the
            // fastest path and is what "max speed" means here. When the user sets
            // a limit, sleep off the remainder of the frame budget so the GPU is
            // not saturated; the cap is applied per iteration, after the work is
            // already done, so it never delays the current detection.
            if (settings_.detection_fps_limit > 0)
            {
                auto const budget = std::chrono::duration<double>(
                    1.0 / static_cast<double>(settings_.detection_fps_limit));
                auto const spent = std::chrono::duration<double>(now_seconds() - frame_started);
                if (spent < budget)
                {
                    std::this_thread::sleep_for(budget - spent);
                }
            }

            // Report the *detection* rate: how fast the engine actually searched
            // for targets this burst, not the wall-clock loop rate. The idle
            // back-off deliberately sleeps the loop on an empty screen, so a raw
            // 1/elapsed figure would read the idle floor (20 fps) as if the
            // pipeline had slowed, when in fact a full detection is still only a
            // millisecond or two. Measuring between frames and dividing by the
            // pipeline time shows the real capability.
            auto const loop_elapsed = now_seconds() - frame_started;
            if (sequence % 15 == 0)
            {
                auto const detection_ms = timings.capture_to_detection_ms;
                auto const detection_rate = detection_ms > 0.0
                    ? 1000.0 / detection_ms : 0.0;
                std::cout << "FRAME #" << sequence
                          << " fps=" << (loop_elapsed > 0.0 ? 1.0 / loop_elapsed : 0.0)
                          << " detection_fps="
                          << (detection_rate > 0.0 ? detection_rate : 0.0)
                          << " capture=" << timings.capture_ms << "ms"
                          << " predict=" << timings.predict_ms << "ms"
                          << " " << command.status << '\n';
            }

            if (frame_limit.has_value() && sequence >= *frame_limit)
            {
                break;
            }
        }
        catch (std::exception const& error)
        {
            tracker_ = {};
            std::cerr << "Loop error: " << error.what() << '\n';
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            if (frame_limit.has_value())
            {
                throw;
            }
        }
    }
    // Stop and join the capture thread before releasing its resources, even if
    // the loop above rethrew: the thread touches the DXGI/GDI captures directly.
    // A bounded run finishes the frame loop without the caller setting `stop`,
    // so signal the capture thread explicitly or the join would wait forever.
    capture_stop_.store(true);
    if (capture_thread.joinable())
    {
        capture_thread.join();
    }
    telemetry.flush();
    dataset_.stop();
    if (input_ != nullptr)
    {
        // Never leave a button held or a pending click queued on exit or error.
        input_->release_buttons();
        input_->close();
    }
    frame_slot_.release();
    if (capture_ != nullptr)
    {
        capture_->release();
    }
    std::cout << "DisabledAssistance native loop stopped\n";
}

void NativeEngine::capture_loop(std::atomic_bool const& stop)
{
    // Geometry is recomputed from the shared settings whenever the GUI changes the
    // FOV, offsets or screen size. It starts from the launch values and is
    // refreshed in place when geometry_dirty_ is set, so the capture region the
    // user sees in the FOV guide is exactly the region the engine searches.
    int live_fov = settings_.fov;
    int left = 0;
    int top = 0;
    auto recompute_origin = [this, &live_fov, &left, &top]() {
        std::lock_guard<std::mutex> lock(geometry_mutex_);
        live_fov = settings_.fov;
        auto const center_offset = live_fov / 2;
        left = static_cast<int>(settings_.width / 2) - center_offset + settings_.offset_x;
        top = static_cast<int>(settings_.height / 2) - center_offset + settings_.offset_y;
    };
    recompute_origin();

    while (!stop.load() && !capture_stop_.load())
    {
        try
        {
            // Apply a live FOV/offset/resolution change before capturing. The
            // backend's initialize() is documented as safe to call again on a
            // size change, and it rebuilds only what depends on the size.
            if (geometry_dirty_.exchange(false))
            {
                recompute_origin();
                auto const expected = static_cast<std::size_t>(live_fov)
                    * static_cast<std::size_t>(live_fov) * 4;
                // Grow the handoff buffers BEFORE the backend starts writing a
                // larger frame, so the producer copy always has room.
                if (!frame_slot_.reserve(expected))
                {
                    std::cerr << "Could not grow the frame slot for the new FOV\n";
                }
                std::string resize_status;
                if (!capture_->initialize(live_fov, resize_status))
                {
                    std::cerr << "Capture resize to FOV " << live_fov << " failed: "
                              << resize_status << '\n';
                    capture_available_.store(false);
                    std::this_thread::sleep_for(std::chrono::milliseconds(50));
                    continue;
                }
                std::cout << "Capture FOV changed to " << live_fov << '\n';
            }

            auto const status = capture_->capture(live_fov, left, top, 0);
            if (!status.ok)
            {
                // A lost device or a display-mode change: report it, mark the
                // frame unavailable, and retry. Until a frame succeeds the
                // consumer sees no new frames rather than stale ones.
                std::cerr << "Capture error: " << status.message << '\n';
                capture_available_.store(false);
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                continue;
            }
            capture_available_.store(true);
            if (!status.had_new_frame)
            {
                // Desktop unchanged: keep the last frame available and poll
                // again shortly, so inference can still run on it.
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }

            // Publish into the slot. A GPU-resident backend supplies a device
            // pointer (device-to-device copy); otherwise upload the host pixels.
            auto const view = capture_->frame();
            auto* write_buffer = frame_slot_.write_buffer();
            if (write_buffer == nullptr)
            {
                continue;
            }
            // Do not overwrite a buffer the consumer may still be reading. The
            // event is a no-op once the consumer has finished copying the frame
            // out (the usual case at these frame rates), so this costs nothing on
            // the fast path while making the two-stream double buffer safe.
            if (consume_event_ != nullptr)
            {
                cudaStreamWaitEvent(capture_stream_, consume_event_, 0);
            }
            auto const expected = static_cast<std::size_t>(live_fov)
                * static_cast<std::size_t>(live_fov) * 4;

            if (view.device_bgra != nullptr)
            {
                // Copy on the dedicated non-blocking stream so it overlaps any
                // inference running on the model's own stream, then record an
                // event. publish() swaps the buffer immediately; the consumer
                // waits on capture_event_ before reading, so the swap stays safe
                // even though the copy has not necessarily finished here.
                if (cudaMemcpyAsync(
                        write_buffer,
                        view.device_bgra,
                        expected,
                        cudaMemcpyDeviceToDevice,
                        capture_stream_
                    ) == cudaSuccess)
                {
                    if (capture_event_ != nullptr)
                    {
                        cudaEventRecord(capture_event_, capture_stream_);
                    }
                    frame_slot_.publish(expected);
                }
            }
            else if (view.cpu_frame != nullptr && !view.cpu_frame->empty())
            {
                if (cudaMemcpy(
                        write_buffer,
                        view.cpu_frame->data(),
                        view.cpu_frame->size(),
                        cudaMemcpyHostToDevice
                    ) == cudaSuccess)
                {
                    frame_slot_.publish(view.cpu_frame->size());
                }
            }
        }
        catch (std::exception const& error)
        {
            std::cerr << "Capture error: " << error.what() << '\n';
            capture_available_.store(false);
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
}

std::string NativeEngine::active_capture() const
{
    std::lock_guard<std::mutex> lock(text_mutex_);
    return active_capture_text_;
}

std::string NativeEngine::active_input() const
{
    std::lock_guard<std::mutex> lock(text_mutex_);
    return active_input_text_;
}
} // namespace aimassist
