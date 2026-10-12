#pragma once

#include "aimassist/detection.hpp"
#include "aimassist/kalman.hpp"
#include "aimassist/settings.hpp"

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace aimassist
{
inline constexpr float movement_deadzone_px = 1.0F;
inline constexpr float on_target_tolerance_px = 2.0F;
inline constexpr double target_lost_grace_seconds = 0.25;
inline constexpr float target_priority_switch_margin_px = 16.0F;

struct TrackerState
{
    std::optional<Vec2> previous_target_center;
    std::optional<Vec2> previous_aim_center;
    std::optional<double> last_target_seen_at;
    std::optional<Vec2> filtered_target_center;
    Vec2 filtered_target_velocity{};
    std::optional<double> previous_filter_time;
    std::optional<double> target_lock_started_at;
    std::optional<double> last_click_at;
    float movement_remainder_x{};
    float movement_remainder_y{};
    float lock_smoothness_remainder_x{};
    float lock_smoothness_remainder_y{};
    // Total movement emitted since the FOV centre was the crosshair's position,
    // i.e. how far the crosshair has been pushed from the screen centre. The
    // detection is reported relative to the FOV centre, but once the crosshair has
    // been moved the remaining error is the target's offset MINUS this applied
    // offset. Without it every frame re-adds the whole centre-to-target distance
    // and the aim runs away from the target instead of locking onto it.
    float applied_offset_x{};
    float applied_offset_y{};
    // Kalman-based estimate/prediction of the aim point (see kalman.hpp).
    Kalman2D aim_filter{};
    // Per-axis velocity scaling and the reset threshold, mirrored from the
    // settings each frame so a live change takes effect immediately.
    float kalman_speed_multiplier_x{1.0F};
    float kalman_speed_multiplier_y{1.0F};
    float kalman_reset_threshold{400.0F};
};

struct AssistCommand
{
    int move_x{};
    int move_y{};
    bool click{};
    bool send{};
    bool has_target{};
    float confidence{};
    Vec2 aim_point{};
    Vec2 aim_error{};
    std::string status;
};

std::pair<int, float> movement_step(
    float error,
    float smoothness,
    float remainder,
    std::string const& aiming_curve
);

Vec2 get_aim_point(Detection const& box, float aim_height);
Vec2 predict_aim_point(Vec2 aim_point, Vec2 velocity, float prediction_horizon_ms);
bool is_on_target(Vec2 aim_point, float center);
bool click_is_due(
    bool lock_active,
    bool on_target,
    double lock_elapsed_ms,
    int shot_delay_ms,
    bool shoot_active,
    std::optional<double> last_click_at,
    double now,
    int shot_interval_ms
);

std::optional<std::size_t> select_target_index(
    std::vector<Detection> const& detections,
    std::optional<Vec2> previous_target_center,
    float center_offset,
    std::optional<float> max_match_distance = std::nullopt
);

std::size_t prioritize_more_centered_target(
    std::vector<Detection> const& detections,
    std::size_t current_index,
    float center_offset,
    int fov
);

// Rank every detection by the configured priority mode and return the index of
// the best one, or std::nullopt when the list is empty.
//
// Modes (string values stored in the config, matching TARGET_PRIORITY_MODES in
// the Python engine):
//   "closest"    -- nearest centre to the crosshair (the historical behaviour);
//   "confidence" -- highest detection score;
//   "distance"   -- largest box, a proxy for the nearest opponent;
//   "hybrid"     -- confidence weighted by closeness to the crosshair;
//   "sticky"     -- closeness, but heavily biased toward the current target.
// `previous_target_center` biases "sticky" and is ignored by the others.
std::optional<std::size_t> select_target_by_mode(
    std::vector<Detection> const& detections,
    std::string const& mode,
    std::optional<Vec2> previous_target_center,
    float center_offset
);

// Multiplier applied to the switch margin for a stickiness level 0-4. Higher
// levels demand a much better rival before the held target is given up, which
// is what stops two close detections from fighting over the crosshair.
float stickiness_margin_factor(int stickiness);

bool target_reference_is_valid(
    std::optional<Vec2> previous_target_center,
    std::optional<double> last_seen_at,
    double now,
    double grace_seconds
);

std::vector<Detection> filter_circle_fov(
    std::vector<Detection> const& detections,
    float center_offset,
    std::string const& fov_shape
);

std::vector<Detection> detections_above_confidence(
    std::vector<Detection> const& detections,
    float threshold
);

std::vector<Detection> top_detections_by_confidence(
    std::vector<Detection> const& detections,
    int limit
);

AssistCommand process_detections(
    std::vector<Detection> detections,
    Settings const& settings,
    TrackerState& state,
    bool lock_active,
    bool shoot_active,
    double now
);
} // namespace aimassist
