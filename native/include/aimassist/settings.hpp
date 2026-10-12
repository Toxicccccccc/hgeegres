#pragma once

#include <string>

namespace aimassist
{
struct Settings
{
    std::string model_path;
    std::string port{"COM6"};
    std::string lock_key{"Alt"};
    std::string shoot_input{"Left mouse"};
    std::string aiming_curve{"Linear"};
    std::string fov_shape{"Square"};
    // Capture backend name: "dxgi" (default), "gdi", or "synthetic".
    std::string capture_backend{"dxgi"};
    // Input provider name: "arduino" (default) or "simulated".
    std::string input_backend{"arduino"};
    int fov{320};
    int width{1920};
    int height{1080};
    int offset_x{0};
    int offset_y{0};
    int detection_limit{5};
    int shot_delay_ms{150};
    int shot_interval_ms{250};
    int prediction_horizon_ms{20};
    float aim_height{100.0F};
    float smoothness{1.0F};
    float lock_smoothness{1.0F};
    float confidence_threshold{0.25F};
    float action_confidence_threshold{0.50F};
    // NMS overlap threshold: two boxes overlapping more than this are merged.
    float iou_threshold{0.45F};
    // Prediction is on by default: it is what keeps a moving target covered, and
    // without it the aim always trails by one pipeline period.
    bool prediction_enabled{true};
    // Movement generation method: "sigmadrift" (default, biomechanical model) or
    // "legacy" (the original per-frame distance-gain correction).
    std::string movement_method{"sigmadrift"};
    // SigmaDrift tuning, mirrored from the Python engine's sigmadrift_* keys so
    // both backends produce the same trajectory for the same settings. The
    // native engine previously ignored these entirely and always used the
    // defaults, so changing them in the GUI had no effect on the .engine path.
    //
    // Snap is the one control that matters day to day: it scales SigmaDrift's
    // movement time, so 0 is a slow, deliberate human stroke and 100 is an
    // immediate lock. The biomechanical defaults (a=50,b=150) model deliberate
    // pointing and are far too slow for aim assist, so the default snap maps to
    // a fast, decisive acquisition instead.
    float sigmadrift_target_width{20.0F};
    float sigmadrift_curvature_scale{0.025F};
    float sigmadrift_overshoot_prob{0.15F};
    float sigmadrift_ou_sigma{1.2F};
    float sigmadrift_tremor_amp_max{0.55F};
    float sigmadrift_sdn_k{0.04F};
    float sigmadrift_sample_dt_mean{7.8F};
    // 0-100. Higher closes the gap faster with less visible biomechanical drift.
    float sigmadrift_snap{80.0F};
    // Hard lock computes a direct correction from the raw detection plus
    // prediction rather than a lagging movement trajectory. lock_smoothness may
    // still scale that correction to make a held lock ease onto the target.
    //
    // On by default: it is the mode that actually follows a moving target. The
    // trajectory/smoothing modes are opt-in for anyone who wants the human-like
    // motion instead of accuracy.
    bool hard_lock{true};
    // Recoil compensation keeps the aim pinned to the tracked target while a
    // burst is in progress, instead of letting the crosshair ride the weapon
    // kick upward off the head.
    bool recoil_compensation{true};
    // 0-100. How strongly the aim is held down against vertical kick; higher
    // holds harder, lower allows more natural rise.
    float recoil_strength{65.0F};
    // Accessibility movement shaping (see movement.hpp).
    bool movement_smoothing_enabled{true};
    float movement_max_step_px{60.0F};
    float movement_acceleration{0.35F};
    float movement_stop_tolerance_px{1.5F};
    // Target selection: how a target is ranked, how stubbornly it is held, and
    // how long a lost target is remembered. "target_priority_mode" is one of
    // "closest", "confidence", "distance", "hybrid" or "sticky"; the other
    // values tune the hold behaviour independently of that ranking.
    //
    // The default behaviour is the simple one players expect: lock one target,
    // then follow the closest to the crosshair, and never swap mid-lock. So the
    // mode is "closest" and focus_single_target is on -- once a target is held it
    // is followed until it is genuinely gone, not re-decided every frame.
    std::string target_priority_mode{"closest"};
    // 0 (switch immediately) to 4 (hold unless badly beaten). Only consulted when
    // focus_single_target is off.
    int target_stickiness{2};
    // When true the engine keeps one target across frames instead of re-picking
    // the best box every frame.
    bool focus_single_target{true};
    // Milliseconds a target centre is remembered after its last detection.
    int target_lost_grace_ms{150};
    // Pixels a new detection may be from the lost centre and still be the same target.
    int reacquire_radius_px{240};
    // Kalman target-prediction filter. "kalman_enabled" keeps the smoothed
    // estimate tracking the box; process/measurement noise trade responsiveness
    // against jitter; the per-axis speed multipliers scale the learned velocity;
    // and the reset threshold reinitialises the filter when a new measurement
    // lands implausibly far from the estimate (a target switch).
    bool kalman_enabled{true};
    float kalman_process_noise{40.0F};
    float kalman_measurement_noise{35.0F};
    float kalman_speed_multiplier_x{1.0F};
    float kalman_speed_multiplier_y{1.0F};
    float kalman_reset_threshold{400.0F};
    // Diagnostics. CSV telemetry is opt-in: it is a measurement tool, not
    // something a normal session pays for, because the loop is uncapped and a
    // per-frame log grows without limit. When enabled it is still rate-limited
    // and capped by the writer.
    bool telemetry_csv_enabled{false};
    // When no target has been seen for a short run of frames the loop holds this
    // frame rate instead of running flat out, so an idle desktop costs little.
    bool idle_backoff_enabled{false};
    int idle_fps_floor{20};
    // Live preview streaming to the GUI: frames are downsampled and emitted as
    // base64 lines at a fixed cadence, decoupled from the inference rate.
    bool preview_stream_enabled{true};
    int preview_fps{20};
    // Pixel size of each streamed preview (square, BGRA-downsampled).
    int preview_size{240};
    // Optional cap on detections per second. 0 means unlimited: the loop runs as
    // fast as capture and inference allow, which is the default and the fastest
    // path. A non-zero value throttles the loop so the GPU can be left some
    // headroom, at the cost of detection rate.
    int detection_fps_limit{0};
    // Skip the model call while the bound lock input is released.
    bool inference_only_when_aiming{false};
    // Labelled-data collection for later model retraining.
    bool dataset_enabled{false};
    bool dataset_save_frames{true};
    float dataset_min_confidence{0.55F};
    int dataset_max_frames_per_second{5};
    std::string dataset_dir{"dataset"};
    std::string dataset_class_names;
};

Settings default_settings();
Settings load_settings(std::string const& path);
} // namespace aimassist
