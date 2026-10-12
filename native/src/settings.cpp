#include "aimassist/settings.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

namespace
{
void skip_whitespace(std::string const& text, std::size_t& index)
{
    while (index < text.size() && std::isspace(static_cast<unsigned char>(text[index])))
    {
        ++index;
    }
}

char peek(std::string const& text, std::size_t index)
{
    return index < text.size() ? text[index] : '\0';
}

std::string parse_string(std::string const& text, std::size_t& index)
{
    if (peek(text, index) != '"')
    {
        throw std::runtime_error("Expected a JSON string.");
    }
    ++index;
    std::string value;
    while (index < text.size())
    {
        auto const current = text[index++];
        if (current == '"')
        {
            return value;
        }
        if (current != '\\')
        {
            value.push_back(current);
            continue;
        }
        if (index >= text.size())
        {
            throw std::runtime_error("Unterminated JSON string escape.");
        }
        auto const escaped = text[index++];
        switch (escaped)
        {
        case '"':
        case '\\':
        case '/':
            value.push_back(escaped);
            break;
        case 'b':
            value.push_back('\b');
            break;
        case 'f':
            value.push_back('\f');
            break;
        case 'n':
            value.push_back('\n');
            break;
        case 'r':
            value.push_back('\r');
            break;
        case 't':
            value.push_back('\t');
            break;
        case 'u':
            index += 4;
            break;
        default:
            value.push_back(escaped);
            break;
        }
    }
    throw std::runtime_error("Unterminated JSON string.");
}

std::string parse_literal(std::string const& text, std::size_t& index)
{
    auto const start = index;
    while (index < text.size())
    {
        auto const current = text[index];
        if (std::isspace(static_cast<unsigned char>(current))
            || current == ',' || current == '}' || current == ']')
        {
            break;
        }
        ++index;
    }
    return text.substr(start, index - start);
}

std::unordered_map<std::string, std::string> parse_object(std::string const& text)
{
    std::size_t index = 0;
    skip_whitespace(text, index);
    if (peek(text, index) != '{')
    {
        throw std::runtime_error("Settings file must contain a JSON object.");
    }
    ++index;

    std::unordered_map<std::string, std::string> values;
    while (true)
    {
        skip_whitespace(text, index);
        if (peek(text, index) == '}')
        {
            break;
        }
        auto const key = parse_string(text, index);
        skip_whitespace(text, index);
        if (peek(text, index) != ':')
        {
            throw std::runtime_error("Expected ':' after JSON key " + key);
        }
        ++index;
        skip_whitespace(text, index);
        std::string value;
        if (peek(text, index) == '"')
        {
            value = parse_string(text, index);
        }
        else
        {
            value = parse_literal(text, index);
        }
        values.emplace(key, std::move(value));
        skip_whitespace(text, index);
        if (peek(text, index) == ',')
        {
            ++index;
            continue;
        }
        if (peek(text, index) == '}')
        {
            break;
        }
        throw std::runtime_error("Expected ',' or '}' in settings JSON.");
    }
    return values;
}

float as_float(std::unordered_map<std::string, std::string> const& values, char const* key, float fallback)
{
    auto const found = values.find(key);
    if (found == values.end())
    {
        return fallback;
    }
    return std::stof(found->second);
}

int as_int(std::unordered_map<std::string, std::string> const& values, char const* key, int fallback)
{
    auto const found = values.find(key);
    if (found == values.end())
    {
        return fallback;
    }
    return static_cast<int>(std::lround(std::stod(found->second)));
}

bool as_bool(std::unordered_map<std::string, std::string> const& values, char const* key, bool fallback)
{
    auto const found = values.find(key);
    if (found == values.end())
    {
        return fallback;
    }
    return found->second == "true" || found->second == "1";
}

std::string as_string(
    std::unordered_map<std::string, std::string> const& values,
    char const* key,
    std::string const& fallback
)
{
    auto const found = values.find(key);
    return found == values.end() ? fallback : found->second;
}

float normalize_confidence(float value)
{
    if (value > 1.0F)
    {
        return value / 100.0F;
    }
    return value;
}
} // namespace

namespace aimassist
{
Settings default_settings()
{
    return {};
}

Settings load_settings(std::string const& path)
{
    std::ifstream file(path);
    if (!file)
    {
        throw std::runtime_error("Cannot open settings file: " + path);
    }
    std::string text((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    auto const values = parse_object(text);
    auto settings = default_settings();
    settings.model_path = as_string(values, "model_path", settings.model_path);
    settings.port = as_string(values, "port", settings.port);
    settings.lock_key = as_string(values, "lock_key", settings.lock_key);
    settings.shoot_input = as_string(values, "shoot_input", settings.shoot_input);
    settings.aiming_curve = as_string(values, "aiming_curve", settings.aiming_curve);
    settings.fov_shape = as_string(values, "fov_shape", settings.fov_shape);
    settings.capture_backend = as_string(values, "capture_backend", settings.capture_backend);
    settings.input_backend = as_string(values, "input_backend", settings.input_backend);
    settings.fov = as_int(values, "fov", settings.fov);
    settings.width = as_int(values, "width", settings.width);
    settings.height = as_int(values, "height", settings.height);
    settings.offset_x = as_int(values, "offset_x", settings.offset_x);
    settings.offset_y = as_int(values, "offset_y", settings.offset_y);
    settings.detection_limit = as_int(values, "detection_limit", settings.detection_limit);
    settings.shot_delay_ms = as_int(values, "shot_delay_ms", settings.shot_delay_ms);
    settings.shot_interval_ms = as_int(values, "shot_interval_ms", settings.shot_interval_ms);
    settings.prediction_horizon_ms = as_int(values, "prediction_horizon_ms", settings.prediction_horizon_ms);
    settings.aim_height = as_float(values, "aim_height", settings.aim_height);
    settings.smoothness = std::clamp(
        as_float(values, "smoothness", settings.smoothness), 1.0F, 20.0F
    );
    settings.lock_smoothness = std::clamp(
        as_float(values, "lock_smoothness", settings.lock_smoothness), 1.0F, 10.0F
    );
    // Movement generation method: "sigmadrift" (default) or "legacy".
    settings.movement_method = as_string(values, "movement_method", settings.movement_method);
    // SigmaDrift tuning keys, read under the same names the Python engine uses.
    settings.sigmadrift_target_width = as_float(
        values, "sigmadrift_target_width", settings.sigmadrift_target_width
    );
    settings.sigmadrift_curvature_scale = as_float(
        values, "sigmadrift_curvature_scale", settings.sigmadrift_curvature_scale
    );
    settings.sigmadrift_overshoot_prob = as_float(
        values, "sigmadrift_overshoot_prob", settings.sigmadrift_overshoot_prob
    );
    settings.sigmadrift_ou_sigma = as_float(
        values, "sigmadrift_ou_sigma", settings.sigmadrift_ou_sigma
    );
    settings.sigmadrift_tremor_amp_max = as_float(
        values, "sigmadrift_tremor_amp_max", settings.sigmadrift_tremor_amp_max
    );
    settings.sigmadrift_sdn_k = as_float(
        values, "sigmadrift_sdn_k", settings.sigmadrift_sdn_k
    );
    settings.sigmadrift_sample_dt_mean = as_float(
        values, "sigmadrift_sample_dt_mean", settings.sigmadrift_sample_dt_mean
    );
    // Snap and recoil compensation are the two day-to-day controls; clamp them
    // to their documented ranges so a hand-edited config cannot invert them.
    settings.sigmadrift_snap = std::clamp(
        as_float(values, "sigmadrift_snap", settings.sigmadrift_snap), 0.0F, 100.0F
    );
    settings.hard_lock = as_bool(values, "hard_lock", settings.hard_lock);
    settings.recoil_compensation = as_bool(
        values, "recoil_compensation", settings.recoil_compensation
    );
    settings.recoil_strength = std::clamp(
        as_float(values, "recoil_strength", settings.recoil_strength), 0.0F, 100.0F
    );
    settings.movement_smoothing_enabled = as_bool(
        values, "movement_smoothing_enabled", settings.movement_smoothing_enabled
    );
    settings.movement_max_step_px = as_float(
        values, "movement_max_step_px", settings.movement_max_step_px
    );
    settings.movement_acceleration = as_float(
        values, "movement_acceleration", settings.movement_acceleration
    );
    settings.movement_stop_tolerance_px = as_float(
        values, "movement_stop_tolerance_px", settings.movement_stop_tolerance_px
    );
    settings.dataset_enabled = as_bool(values, "dataset_enabled", settings.dataset_enabled);
    settings.dataset_save_frames = as_bool(
        values, "dataset_save_frames", settings.dataset_save_frames
    );
    settings.dataset_min_confidence = as_float(
        values, "dataset_min_confidence", settings.dataset_min_confidence
    );
    settings.dataset_max_frames_per_second = as_int(
        values, "dataset_max_frames_per_second", settings.dataset_max_frames_per_second
    );
    settings.dataset_dir = as_string(values, "dataset_dir", settings.dataset_dir);
    settings.dataset_class_names = as_string(
        values, "dataset_class_names", settings.dataset_class_names
    );
    settings.target_priority_mode = as_string(
        values, "target_priority_mode", settings.target_priority_mode
    );
    settings.target_stickiness = as_int(
        values, "target_stickiness", settings.target_stickiness
    );
    settings.focus_single_target = as_bool(
        values, "focus_single_target", settings.focus_single_target
    );
    settings.target_lost_grace_ms = as_int(
        values, "target_lost_grace_ms", settings.target_lost_grace_ms
    );
    settings.reacquire_radius_px = as_int(
        values, "reacquire_radius_px", settings.reacquire_radius_px
    );
    // Kalman target-prediction filter tuning.
    settings.kalman_enabled = as_bool(values, "kalman_enabled", settings.kalman_enabled);
    settings.kalman_process_noise = as_float(
        values, "kalman_process_noise", settings.kalman_process_noise
    );
    settings.kalman_measurement_noise = as_float(
        values, "kalman_measurement_noise", settings.kalman_measurement_noise
    );
    settings.kalman_speed_multiplier_x = as_float(
        values, "kalman_speed_multiplier_x", settings.kalman_speed_multiplier_x
    );
    settings.kalman_speed_multiplier_y = as_float(
        values, "kalman_speed_multiplier_y", settings.kalman_speed_multiplier_y
    );
    settings.kalman_reset_threshold = as_float(
        values, "kalman_reset_threshold", settings.kalman_reset_threshold
    );
    settings.telemetry_csv_enabled = as_bool(
        values, "telemetry_csv_enabled", settings.telemetry_csv_enabled
    );
    settings.idle_backoff_enabled = as_bool(
        values, "idle_backoff_enabled", settings.idle_backoff_enabled
    );
    settings.idle_fps_floor = as_int(
        values, "idle_fps_floor", settings.idle_fps_floor
    );
    settings.preview_stream_enabled = as_bool(
        values, "preview_stream_enabled", settings.preview_stream_enabled
    );
    settings.preview_fps = as_int(values, "preview_fps", settings.preview_fps);
    settings.preview_size = as_int(values, "preview_size", settings.preview_size);
    // Optional detection-rate cap. 0 (the default) means unlimited: run flat out.
    settings.detection_fps_limit = as_int(
        values, "detection_fps_limit", settings.detection_fps_limit
    );
    settings.inference_only_when_aiming = as_bool(
        values, "inference_only_when_aiming", settings.inference_only_when_aiming
    );
    settings.confidence_threshold = normalize_confidence(
        as_float(values, "confidence_threshold", settings.confidence_threshold * 100.0F)
    );
    settings.action_confidence_threshold = normalize_confidence(
        as_float(values, "action_confidence_threshold", settings.action_confidence_threshold * 100.0F)
    );
    // NMS overlap: stored 0-1, passed straight through (unlike the confidences,
    // which are stored 0-100 by some builds).
    settings.iou_threshold = as_float(values, "iou_threshold", settings.iou_threshold);
    settings.prediction_enabled = as_bool(values, "prediction_enabled", settings.prediction_enabled);
    if (settings.fov <= 0 || settings.width <= 0 || settings.height <= 0
        || settings.detection_limit <= 0 || settings.smoothness <= 0.0F)
    {
        throw std::runtime_error("Settings contain invalid capture or smoothness values.");
    }
    // Clamp the accessibility movement bounds so a bad configuration cannot
    // produce unbounded movement or an inverted acceleration ramp.
    settings.movement_max_step_px = std::clamp(settings.movement_max_step_px, 1.0F, 400.0F);
    settings.movement_acceleration = std::clamp(settings.movement_acceleration, 0.01F, 1.0F);
    settings.movement_stop_tolerance_px = std::clamp(
        settings.movement_stop_tolerance_px, 0.0F, 32.0F
    );
    settings.dataset_min_confidence = std::clamp(settings.dataset_min_confidence, 0.0F, 1.0F);
    // (Kalman clamps live with the other targeting clamps further down.)
    settings.dataset_max_frames_per_second = std::clamp(
        settings.dataset_max_frames_per_second, 1, 60
    );
    if (settings.dataset_dir.empty())
    {
        settings.dataset_dir = "dataset";
    }
    // Validate the targeting values so a hand-edited config cannot select an
    // unknown mode or invert the stickiness range.
    static constexpr char const* known_modes[] = {
        "closest", "confidence", "distance", "hybrid", "sticky"
    };
    bool mode_known = false;
    for (auto const* mode : known_modes)
    {
        if (settings.target_priority_mode == mode)
        {
            mode_known = true;
            break;
        }
    }
    if (!mode_known)
    {
        settings.target_priority_mode = "closest";
    }
    settings.target_stickiness = std::clamp(settings.target_stickiness, 0, 4);
    settings.target_lost_grace_ms = std::clamp(settings.target_lost_grace_ms, 0, 2000);
    settings.reacquire_radius_px = std::clamp(settings.reacquire_radius_px, 0, 600);
    // Keep the Kalman parameters inside the ranges the filter clamps to, so a
    // hand-edited config cannot push the estimator into a degenerate state.
    settings.kalman_process_noise = std::clamp(settings.kalman_process_noise, 1.0e-4F, 5000.0F);
    settings.kalman_measurement_noise = std::clamp(
        settings.kalman_measurement_noise, 1.0e-4F, 5000.0F
    );
    settings.kalman_speed_multiplier_x = std::clamp(
        settings.kalman_speed_multiplier_x, 0.1F, 3.0F
    );
    settings.kalman_speed_multiplier_y = std::clamp(
        settings.kalman_speed_multiplier_y, 0.1F, 3.0F
    );
    settings.kalman_reset_threshold = std::clamp(
        settings.kalman_reset_threshold, 0.0F, 2000.0F
    );
    settings.iou_threshold = std::clamp(settings.iou_threshold, 0.0F, 1.0F);
    settings.idle_fps_floor = std::clamp(settings.idle_fps_floor, 1, 144);
    settings.preview_fps = std::clamp(settings.preview_fps, 1, 60);
    settings.preview_size = std::clamp(settings.preview_size, 64, 512);
    // 0 = unlimited; otherwise a sane ceiling. A tiny non-zero value would only
    // starve the assistant, so the floor when set is 1 fps.
    if (settings.detection_fps_limit < 0)
    {
        settings.detection_fps_limit = 0;
    }
    else if (settings.detection_fps_limit > 1000)
    {
        settings.detection_fps_limit = 1000;
    }
    return settings;
}
} // namespace aimassist
