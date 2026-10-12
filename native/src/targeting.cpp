#include "aimassist/targeting.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace
{
// Tuning for the adaptive distance-scaled gain (see movement_step).
constexpr float fast_snap_gain = 0.45F;
constexpr float max_speed_boost = 1.6F;

float hypot2(float dx, float dy)
{
    return std::sqrt(dx * dx + dy * dy);
}

aimassist::Vec2 box_center(aimassist::Detection const& box)
{
    return {(box.x1 + box.x2) * 0.5F, (box.y1 + box.y2) * 0.5F};
}

std::size_t max_confidence_index(std::vector<aimassist::Detection> const& detections)
{
    return static_cast<std::size_t>(std::max_element(
        detections.begin(),
        detections.end(),
        [](aimassist::Detection const& left, aimassist::Detection const& right)
        {
            return left.confidence < right.confidence;
        }
    ) - detections.begin());
}

std::pair<int, float> smooth_lock_step(float step, float smoothness, float remainder)
{
    auto const divisor = std::clamp(smoothness, 1.0F, 10.0F);
    auto const scaled = step / divisor + remainder;
    auto const movement = static_cast<int>(std::lround(scaled));
    return {movement, scaled - static_cast<float>(movement)};
}
} // namespace

namespace aimassist
{
std::pair<int, float> movement_step(
    float error,
    float smoothness,
    float remainder,
    std::string const& aiming_curve
)
{
    if (std::abs(error) <= movement_deadzone_px)
    {
        return {0, 0.0F};
    }

    auto const curve_input = std::min(std::abs(error) / 64.0F, 1.0F);
    float curve_output = curve_input;
    if (aiming_curve == "Linear")
    {
        curve_output = curve_input;
    }
    else if (aiming_curve == "Quadratic" || aiming_curve == "Ease In")
    {
        // The Aim page/presets name the curves Quadratic/Cubic/Rational, but the
        // engine only knew the "Ease ..." spellings and threw on anything else, so
        // any preset that set one of these made every frame fail. Accept both sets
        // (the old names stay as aliases) and mirror the Python engine exactly.
        curve_output = curve_input * curve_input;
    }
    else if (aiming_curve == "Cubic")
    {
        curve_output = curve_input * curve_input * curve_input;
    }
    else if (aiming_curve == "Rational")
    {
        auto const squared = curve_input * curve_input;
        curve_output = squared < 1.0F ? squared / (2.0F - squared) : 1.0F;
    }
    else if (aiming_curve == "Ease Out")
    {
        curve_output = 1.0F - (1.0F - curve_input) * (1.0F - curve_input);
    }
    else if (aiming_curve == "Ease In-Out")
    {
        curve_output = curve_input * curve_input * (3.0F - 2.0F * curve_input);
    }
    else if (aiming_curve == "Bezier")
    {
        float lower = 0.0F;
        float upper = 1.0F;
        for (int index = 0; index < 12; ++index)
        {
            auto const parameter = (lower + upper) * 0.5F;
            auto const one_minus = 1.0F - parameter;
            auto const x = 3.0F * one_minus * one_minus * parameter * 0.25F
                + 3.0F * one_minus * parameter * parameter * 0.25F
                + parameter * parameter * parameter;
            if (x < curve_input)
            {
                lower = parameter;
            }
            else
            {
                upper = parameter;
            }
        }
        auto const parameter = (lower + upper) * 0.5F;
        auto const one_minus = 1.0F - parameter;
        curve_output = 3.0F * one_minus * one_minus * parameter * 0.1F
            + 3.0F * one_minus * parameter * parameter
            + parameter * parameter * parameter;
    }
    else
    {
        throw std::invalid_argument("Unsupported aiming curve: " + aiming_curve);
    }

    // Adaptive movement, inspired by the reference's speed-multiplier model:
    // the applied gain ramps with distance. Far from the target the aim moves
    // decisively; close to it the gain collapses so the crosshair settles
    // instead of oscillating -- which is exactly what a player who cannot make
    // fine corrections by hand needs.
    auto const magnitude = std::abs(error);
    auto const snap_radius = 24.0F;
    auto const near_radius = 96.0F;
    auto const max_distance = 256.0F;

    float distance_gain = curve_output;
    if (magnitude < snap_radius)
    {
        // Very close: a small fixed boost so the final pixels are still crossed.
        distance_gain = fast_snap_gain * 0.5F + curve_output * fast_snap_gain * 0.5F;
    }
    else if (magnitude < near_radius)
    {
        auto const t = magnitude / near_radius;
        auto const ramp = 1.0F - (1.0F - t) * (1.0F - t);
        distance_gain = fast_snap_gain + (1.0F - fast_snap_gain) * ramp;
    }
    else
    {
        auto const t = std::clamp((magnitude - near_radius) / (max_distance - near_radius), 0.0F, 1.0F);
        distance_gain = 1.0F + max_speed_boost * t;
    }
    distance_gain *= 1.0F - 0.5F * (1.0F - curve_output);

    // Saved configs may contain the old 0.1 minimum even though larger
    // smoothness means gentler movement. Normalize that legacy value and keep
    // every step within the remaining error so it cannot overshoot and oscillate.
    auto const response = std::clamp(smoothness, 1.0F, 20.0F);
    auto const gain = std::clamp(distance_gain / response, 0.0F, 1.0F);
    auto scaled = error * gain + remainder;
    if (scaled * error <= 0.0F)
    {
        return {0, 0.0F};
    }
    if (std::abs(scaled) > std::abs(error))
    {
        scaled = error;
    }
    auto const movement = static_cast<int>(scaled);
    return {movement, scaled - static_cast<float>(movement)};
}

Vec2 get_aim_point(Detection const& box, float aim_height)
{
    return {
        (box.x1 + box.x2) * 0.5F,
        box.y2 - (box.y2 - box.y1) * (aim_height / 100.0F)
    };
}

Vec2 predict_aim_point(Vec2 aim_point, Vec2 velocity, float prediction_horizon_ms)
{
    auto const horizon_seconds = prediction_horizon_ms / 1000.0F;
    return {
        aim_point.x + velocity.x * horizon_seconds,
        aim_point.y + velocity.y * horizon_seconds
    };
}

bool is_on_target(Vec2 aim_point, float center)
{
    return hypot2(aim_point.x - center, aim_point.y - center) <= on_target_tolerance_px;
}

bool click_is_due(
    bool lock_active,
    bool on_target,
    double lock_elapsed_ms,
    int shot_delay_ms,
    bool shoot_active,
    std::optional<double> last_click_at,
    double now,
    int shot_interval_ms
)
{
    return lock_active
        && on_target
        && lock_elapsed_ms >= static_cast<double>(shot_delay_ms)
        && shoot_active
        && (
            !last_click_at.has_value()
            || (now - *last_click_at) * 1000.0 >= static_cast<double>(shot_interval_ms)
        );
}

std::optional<std::size_t> select_target_index(
    std::vector<Detection> const& detections,
    std::optional<Vec2> previous_target_center,
    float center_offset,
    std::optional<float> max_match_distance
)
{
    if (detections.empty())
    {
        return std::nullopt;
    }

    std::vector<std::size_t> order(detections.size());
    std::iota(order.begin(), order.end(), 0);
    std::vector<float> distances(detections.size());
    for (std::size_t index = 0; index < detections.size(); ++index)
    {
        auto const center = box_center(detections[index]);
        auto const reference = previous_target_center.value_or(Vec2{center_offset, center_offset});
        auto const dx = center.x - reference.x;
        auto const dy = center.y - reference.y;
        distances[index] = std::sqrt(dx * dx + dy * dy);
    }

    std::stable_sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right)
    {
        if (distances[left] != distances[right])
        {
            return distances[left] < distances[right];
        }
        return detections[left].confidence > detections[right].confidence;
    });

    auto const selected = order.front();
    if (previous_target_center.has_value()
        && max_match_distance.has_value()
        && distances[selected] > *max_match_distance)
    {
        return std::nullopt;
    }
    return selected;
}

float stickiness_margin_factor(int stickiness)
{
    // Mirrors TARGET_STICKINESS_FACTOR in the Python engine so both engines hold
    // a target with identical strength for the same setting.
    switch (std::clamp(stickiness, 0, 4))
    {
    case 0:
        return 0.0F;
    case 1:
        return 0.5F;
    case 2:
        return 1.0F;
    case 3:
        return 1.75F;
    default:
        return 3.0F;
    }
}

std::optional<std::size_t> select_target_by_mode(
    std::vector<Detection> const& detections,
    std::string const& mode,
    std::optional<Vec2> previous_target_center,
    float center_offset
)
{
    if (detections.empty())
    {
        return std::nullopt;
    }

    auto const reference = previous_target_center.value_or(Vec2{center_offset, center_offset});

    // A single score per detection; the highest wins. Each mode defines its own
    // score so the ranking rule is one place, not scattered through the loop.
    std::size_t best = 0;
    float best_score = -1.0e30F;
    for (std::size_t index = 0; index < detections.size(); ++index)
    {
        auto const box = detections[index];
        auto const center = box_center(box);
        auto const to_crosshair = hypot2(center.x - center_offset, center.y - center_offset);
        auto const to_previous = hypot2(center.x - reference.x, center.y - reference.y);
        auto const area = std::max((box.x2 - box.x1), 0.0F) * std::max((box.y2 - box.y1), 0.0F);

        float score = 0.0F;
        if (mode == "confidence")
        {
            score = box.confidence;
        }
        else if (mode == "distance")
        {
            // Larger box first; confidence only breaks ties.
            score = area * 1.0e-4F + box.confidence * 1.0e-3F;
        }
        else if (mode == "hybrid")
        {
            // Confidence weighted by closeness: a certain, central box wins, but
            // a very confident box off to the side can still beat a weak central one.
            auto const closeness = 1.0F / (1.0F + to_crosshair / std::max(center_offset, 1.0F));
            score = box.confidence * (0.5F + 0.5F * closeness);
        }
        else if (mode == "sticky" && previous_target_center.has_value())
        {
            // Strongly prefer continuity, then closeness to the crosshair.
            score = -to_previous - 0.25F * to_crosshair;
        }
        else
        {
            // "closest" and the sticky fallback before any lock: nearest centre.
            score = -to_crosshair;
        }

        if (score > best_score)
        {
            best_score = score;
            best = index;
        }
    }
    return best;
}

std::size_t prioritize_more_centered_target(
    std::vector<Detection> const& detections,
    std::size_t current_index,
    float center_offset,
    int fov
)
{
    auto const priority = select_target_index(detections, std::nullopt, center_offset);
    if (!priority.has_value())
    {
        return current_index;
    }
    auto const current = box_center(detections[current_index]);
    auto const current_center_distance = hypot2(
        current.x - center_offset,
        current.y - center_offset
    );
    auto const priority_center = box_center(detections[*priority]);
    auto const priority_distance = hypot2(
        priority_center.x - center_offset,
        priority_center.y - center_offset
    );
    auto const switch_margin = std::max(
        target_priority_switch_margin_px,
        static_cast<float>(fov) * 0.05F
    );
    if (*priority != current_index
        && current_center_distance - priority_distance >= switch_margin)
    {
        return *priority;
    }
    return current_index;
}

bool target_reference_is_valid(
    std::optional<Vec2> previous_target_center,
    std::optional<double> last_seen_at,
    double now,
    double grace_seconds
)
{
    return previous_target_center.has_value()
        && last_seen_at.has_value()
        && now - *last_seen_at <= grace_seconds;
}

std::vector<Detection> filter_circle_fov(
    std::vector<Detection> const& detections,
    float center_offset,
    std::string const& fov_shape
)
{
    if (fov_shape != "Circle")
    {
        return detections;
    }
    std::vector<Detection> filtered;
    filtered.reserve(detections.size());
    auto const radius_squared = center_offset * center_offset;
    for (auto const& detection : detections)
    {
        auto const center = box_center(detection);
        auto const dx = center.x - center_offset;
        auto const dy = center.y - center_offset;
        if (dx * dx + dy * dy <= radius_squared)
        {
            filtered.push_back(detection);
        }
    }
    return filtered;
}

std::vector<Detection> detections_above_confidence(
    std::vector<Detection> const& detections,
    float threshold
)
{
    std::vector<Detection> filtered;
    filtered.reserve(detections.size());
    for (auto const& detection : detections)
    {
        if (detection.confidence >= threshold)
        {
            filtered.push_back(detection);
        }
    }
    return filtered;
}

std::vector<Detection> top_detections_by_confidence(
    std::vector<Detection> const& detections,
    int limit
)
{
    auto ranked = detections;
    std::stable_sort(
        ranked.begin(),
        ranked.end(),
        [](Detection const& left, Detection const& right)
        {
            return left.confidence > right.confidence;
        }
    );
    if (static_cast<int>(ranked.size()) > limit)
    {
        ranked.resize(static_cast<std::size_t>(limit));
    }
    return ranked;
}

AssistCommand process_detections(
    std::vector<Detection> detections,
    Settings const& settings,
    TrackerState& state,
    bool lock_active,
    bool shoot_active,
    double now
)
{
    AssistCommand command;
    auto const center_offset = static_cast<float>(settings.fov) * 0.5F;
    auto const captured_detection_count = detections.size();
    detections = filter_circle_fov(detections, center_offset, settings.fov_shape);
    // How long a held target is remembered after it was last seen.
    //
    // While the lock key is HELD the target must be kept: that is the whole point
    // of holding it. This used to collapse the grace to zero while locked, which
    // meant "expire unless seen within 0 seconds" -- always false, because time
    // always advances -- so the target reference was wiped every frame and the aim
    // re-picked a box from scratch each frame, visibly jumping between enemies.
    // A held lock now keeps the target for a full second even if it is briefly
    // occluded or its detection drops out, so it re-locks onto the same enemy
    // when it reappears instead of switching.
    auto const grace_seconds = static_cast<double>(settings.target_lost_grace_ms) / 1000.0;
    auto const reacquire_grace = lock_active ? 1.0 : grace_seconds;
    if (!target_reference_is_valid(
            state.previous_target_center,
            state.last_target_seen_at,
            now,
            reacquire_grace
        ))
    {
        state.previous_target_center.reset();
        state.previous_aim_center.reset();
        state.last_target_seen_at.reset();
    }

    if (detections.empty())
    {
        if (!target_reference_is_valid(
                state.previous_target_center,
                state.last_target_seen_at,
                now,
                reacquire_grace
            ))
        {
            state.previous_target_center.reset();
            state.last_target_seen_at.reset();
        }
        state.target_lock_started_at.reset();
        state.previous_aim_center.reset();
        state.filtered_target_center.reset();
        state.filtered_target_velocity = {};
        state.previous_filter_time.reset();
        state.last_click_at.reset();
        state.movement_remainder_x = 0.0F;
        state.movement_remainder_y = 0.0F;
        state.lock_smoothness_remainder_x = 0.0F;
        state.lock_smoothness_remainder_y = 0.0F;
        // A lost target ends the lock, so the crosshair reference is stale; a new
        // acquisition must start measuring from a clean offset.
        state.applied_offset_x = 0.0F;
        state.applied_offset_y = 0.0F;
        if (captured_detection_count == 0)
        {
            command.status = "No detections in captured area";
        }
        else if (settings.fov_shape == "Circle")
        {
            command.status = "Detections outside circular FOV";
        }
        else
        {
            command.status = "No detections inside FOV";
        }
        return command;
    }

    auto eligible = detections_above_confidence(detections, settings.confidence_threshold);
    if (!state.previous_target_center.has_value())
    {
        eligible = top_detections_by_confidence(eligible, settings.detection_limit);
    }

    bool target_match_missing = false;
    bool target_switched = false;
    bool target_locked = false;
    Detection candidate{};
    bool has_candidate = false;

    if (!eligible.empty())
    {
        // The re-acquire radius is the user-tunable window a new detection may
        // appear in and still be treated as the same target; the fov-based floor
        // keeps a sensible default when the setting is left small.
        auto const lock_radius = std::max(
            static_cast<float>(settings.reacquire_radius_px),
            std::max(48.0F, static_cast<float>(settings.fov) * 0.2F)
        );
        auto const recoil_tracking = lock_active
            && shoot_active
            && settings.recoil_compensation;
        auto const association_radius = recoil_tracking
            ? std::max(lock_radius, static_cast<float>(settings.fov) * 0.45F)
            : lock_radius;
        auto candidate_index = select_target_index(
            eligible,
            state.previous_target_center,
            center_offset,
            association_radius
        );
        if (!candidate_index.has_value())
        {
            // Keep the held target reference until its lock grace expires. A
            // single missed/shifted box must not release the lock and jump to a
            // different candidate; the next frame can then reacquire the same
            // target near its last known position.
            target_match_missing = true;
            candidate = eligible[max_confidence_index(eligible)];
            has_candidate = true;
            eligible.clear();
        }

        if (candidate_index.has_value())
        {
            // Once a target is held, keep it: the only job here is to follow the
            // same box frame to frame, not to re-decide which box is best. That is
            // what "focus one target" means -- the aim does not jump between two
            // enemies because one of them briefly scored higher or sat nearer the
            // centre. The held target is followed by proximity (select_target_index
            // above, inside lock_radius); it is only replaced once it is genuinely
            // gone, which reset previous_target_center and re-picked the closest one
            // to the crosshair before this block ran.
            //
            // The priority-mode ranking still runs when the player has turned focus
            // off, so the older "let a much better rival take over" behaviour stays
            // available for anyone who wants it.
            if (state.previous_target_center.has_value() && !settings.focus_single_target)
            {
                auto const ranked = select_target_by_mode(
                    eligible,
                    settings.target_priority_mode,
                    state.previous_target_center,
                    center_offset
                );
                auto const priority_index = ranked.value_or(*candidate_index);
                auto const current_center = box_center(eligible[*candidate_index]);
                auto const priority_center = box_center(eligible[priority_index]);
                auto const current_distance = hypot2(
                    current_center.x - state.previous_target_center->x,
                    current_center.y - state.previous_target_center->y
                );
                auto const priority_distance = hypot2(
                    priority_center.x - state.previous_target_center->x,
                    priority_center.y - state.previous_target_center->y
                );
                auto const margin = std::max(target_priority_switch_margin_px,
                    static_cast<float>(settings.fov) * 0.05F)
                    * stickiness_margin_factor(settings.target_stickiness);
                bool const rival_wins = priority_index != *candidate_index
                    && current_distance - priority_distance >= margin;
                if (rival_wins)
                {
                    target_switched = priority_index != *candidate_index;
                    candidate_index = priority_index;
                }
            }
            target_locked = state.previous_target_center.has_value() && !target_switched;
            if (target_switched)
            {
                state.previous_aim_center.reset();
                state.filtered_target_center.reset();
                state.filtered_target_velocity = {};
                state.previous_filter_time.reset();
                state.target_lock_started_at.reset();
                state.last_click_at.reset();
                state.movement_remainder_x = 0.0F;
                state.movement_remainder_y = 0.0F;
                state.lock_smoothness_remainder_x = 0.0F;
                state.lock_smoothness_remainder_y = 0.0F;
                // A switched target is a new lock: restart the crosshair reference.
                state.applied_offset_x = 0.0F;
                state.applied_offset_y = 0.0F;
            }
            candidate = eligible[*candidate_index];
            has_candidate = true;
        }
    }
    else
    {
        candidate = detections[max_confidence_index(detections)];
        has_candidate = true;
    }

    if (!has_candidate)
    {
        command.status = "No target detected";
        return command;
    }

    auto aim = get_aim_point(candidate, settings.aim_height);
    auto const target_center = box_center(candidate);
    auto const accepted = !eligible.empty();
    auto const action_allowed = accepted
        && candidate.confidence >= settings.action_confidence_threshold;
    // Recoil compensation. A held trigger drives the view upward, so a burst the
    // player is already holding rises off the head between detections. While the
    // shoot input is active the aim point is biased further down by a fraction of
    // the box height, so the crosshair is pulled back down onto the head instead
    // of riding the kick. The bias is scaled by the box height (a head on a tall
    // box needs a bigger correction than on a small one) and by recoil_strength.
    if (settings.recoil_compensation && shoot_active && action_allowed)
    {
        auto const box_height = std::max(0.0F, candidate.y2 - candidate.y1);
        auto const strength = std::clamp(settings.recoil_strength / 100.0F, 0.0F, 1.0F);
        // Up to 18% of the box height downward at full strength: enough to hold a
        // typical spray on the head without dragging the aim off a crouching or
        // dropping target.
        aim.y += box_height * 0.18F * strength;
    }
    command.has_target = accepted;
    command.confidence = candidate.confidence;
    command.aim_point = aim;

    // The detection is reported relative to the FOV centre, but the crosshair has
    // already been pushed away from the centre by every movement previously sent
    // this lock. The true remaining error is the target's offset from the centre
    // minus that applied offset. Measuring from the centre alone (as this used to)
    // re-added the whole distance every frame, so the aim always overshot and ran
    // away from the target instead of holding it.
    auto const target_offset_x = aim.x - center_offset;
    auto const target_offset_y = aim.y - center_offset;
    float measured_dx = target_offset_x - state.applied_offset_x;
    float measured_dy = target_offset_y - state.applied_offset_y;
    float movement_dx = measured_dx;
    float movement_dy = measured_dy;
    bool on_target = false;
    double lock_elapsed_ms = 0.0;
    Vec2 predicted = aim;

    if (action_allowed)
    {
        // Kalman filter tuning. The user-facing process/measurement noise control
        // how eagerly the estimate follows the raw box versus trusting its own
        // motion model; the per-axis speed multipliers scale the learned velocity;
        // and the reset threshold reinitialises the filter when a new measurement
        // lands implausibly far from the estimate (a target switch), instead of
        // smearing the aim across the gap between two different targets.
        auto kalman_settings = KalmanSettings{};
        // Hard lock disables the smoother: the filter's whole job is to trade lag
        // for steadiness, and a player asking for a rigid lock wants the aim on the
        // detection now, not on a lagging estimate of it. With the filter off the
        // estimator is a pass-through (position = detection exactly, velocity by
        // finite difference), so only the prediction lead remains.
        kalman_settings.enabled = settings.kalman_enabled && !settings.hard_lock;
        kalman_settings.process_noise_position = static_cast<double>(
            settings.kalman_process_noise
        );
        kalman_settings.measurement_noise = static_cast<double>(
            settings.kalman_measurement_noise
        );
        state.aim_filter.set_settings(kalman_settings);
        state.kalman_speed_multiplier_x = settings.kalman_speed_multiplier_x;
        state.kalman_speed_multiplier_y = settings.kalman_speed_multiplier_y;
        state.kalman_reset_threshold = settings.kalman_reset_threshold;

        auto lookahead_seconds = 0.0;
        if (settings.prediction_enabled)
        {
            lookahead_seconds = static_cast<double>(settings.prediction_horizon_ms) / 1000.0;
        }

        if (!target_locked
            || !state.filtered_target_center.has_value()
            || !state.previous_filter_time.has_value()
            || !state.previous_aim_center.has_value())
        {
            // New lock: restart the estimator so the first sample cannot
            // produce a spurious lead.
            state.aim_filter.reset();
        }
        // A large jump between the previous measurement and this one means the
        // held target was lost and a different box is now selected: restart the
        // filter so it does not interpolate between the two.
        if (state.kalman_reset_threshold > 0.0F
            && state.previous_aim_center.has_value())
        {
            auto const jump = hypot2(
                aim.x - state.previous_aim_center->x,
                aim.y - state.previous_aim_center->y
            );
            if (jump > state.kalman_reset_threshold)
            {
                state.aim_filter.reset();
            }
        }
        auto const delta_time = state.previous_filter_time.has_value()
            ? std::max(now - *state.previous_filter_time, 0.001)
            : 0.0;
        auto const telemetry = state.aim_filter.update(aim, delta_time, lookahead_seconds);
        state.filtered_target_center = telemetry.estimate;
        // Scale the learned velocity per axis before it drives the look-ahead, so
        // the speed multipliers take effect on the prediction as well as the
        // reported estimate.
        state.filtered_target_velocity = Vec2{
            telemetry.velocity.x * state.kalman_speed_multiplier_x,
            telemetry.velocity.y * state.kalman_speed_multiplier_y
        };
        state.previous_filter_time = now;

        // Recompute the lead with the scaled velocity so kf speed multipliers
        // actually move the predicted aim point.
        if (lookahead_seconds > 0.0)
        {
            predicted = predict_aim_point(
                telemetry.estimate,
                state.filtered_target_velocity,
                static_cast<float>(settings.prediction_horizon_ms)
            );
        }
        else
        {
            predicted = telemetry.estimate;
        }
        // The predicted aim point is in FOV-centre coordinates; subtract the
        // movement already applied this lock so the step is the remaining error,
        // not the whole centre-to-target distance. Omitting this (as the code
        // used to) re-added the full offset every frame and the aim ran away.
        movement_dx = (predicted.x - center_offset) - state.applied_offset_x;
        movement_dy = (predicted.y - center_offset) - state.applied_offset_y;
        // "On target" is judged on the real remaining error, so the crosshair is
        // considered locked once it genuinely sits on the target, not merely when
        // the target is near the centre of the FOV.
        on_target = hypot2(movement_dx, movement_dy) <= on_target_tolerance_px;
        if (lock_active && on_target)
        {
            if (!state.target_lock_started_at.has_value())
            {
                state.target_lock_started_at = now;
            }
            lock_elapsed_ms = (now - *state.target_lock_started_at) * 1000.0;
        }
        else
        {
            state.target_lock_started_at.reset();
            lock_elapsed_ms = 0.0;
        }
    }
    else
    {
        state.target_lock_started_at.reset();
        state.previous_aim_center.reset();
        state.filtered_target_center.reset();
        state.filtered_target_velocity = {};
        state.previous_filter_time.reset();
    }

    command.aim_error = {measured_dx, measured_dy};

    if (accepted)
    {
        state.previous_target_center = target_center;
        state.previous_aim_center = aim;
        state.last_target_seen_at = now;
        if (!action_allowed)
        {
            command.status = "Below action threshold";
        }
        else if (!lock_active)
        {
            command.status = "Hold lock key";
        }
        else if (!on_target)
        {
            command.status = "Move onto target";
        }
        else if (lock_elapsed_ms >= settings.shot_delay_ms)
        {
            command.status = "Ready";
        }
        else
        {
            command.status = "Settling";
        }
    }

    if (action_allowed)
    {
        if (lock_active)
        {
            if (settings.hard_lock)
            {
                // Hard lock starts from the full direct correction. The lock
                // smoothness control below may scale the emitted step.
                command.move_x = static_cast<int>(std::lround(movement_dx));
                command.move_y = static_cast<int>(std::lround(movement_dy));
                state.movement_remainder_x = 0.0F;
                state.movement_remainder_y = 0.0F;
            }
            else
            {
                auto const x_step = movement_step(
                    movement_dx,
                    settings.smoothness,
                    state.movement_remainder_x,
                    settings.aiming_curve
                );
                auto const y_step = movement_step(
                    movement_dy,
                    settings.smoothness,
                    state.movement_remainder_y,
                    settings.aiming_curve
                );
                command.move_x = x_step.first;
                command.move_y = y_step.first;
                state.movement_remainder_x = x_step.second;
                state.movement_remainder_y = y_step.second;
            }
        }
        else
        {
            command.move_x = 0;
            command.move_y = 0;
            state.movement_remainder_x = 0.0F;
            state.movement_remainder_y = 0.0F;
            state.lock_smoothness_remainder_x = 0.0F;
            state.lock_smoothness_remainder_y = 0.0F;
            // Lock not held: the crosshair reference no longer tracks a lock, so
            // clear it and let the next hold measure from a fresh start.
            state.applied_offset_x = 0.0F;
            state.applied_offset_y = 0.0F;
        }
        if (lock_active)
        {
            auto const x_step = smooth_lock_step(
                static_cast<float>(command.move_x),
                settings.lock_smoothness,
                state.lock_smoothness_remainder_x
            );
            auto const y_step = smooth_lock_step(
                static_cast<float>(command.move_y),
                settings.lock_smoothness,
                state.lock_smoothness_remainder_y
            );
            command.move_x = x_step.first;
            command.move_y = y_step.first;
            state.lock_smoothness_remainder_x = x_step.second;
            state.lock_smoothness_remainder_y = y_step.second;
        }
        // Record the movement that will actually be sent. Next frame the detection
        // is still relative to the FOV centre, so the crosshair's new position is
        // the running total of everything emitted; subtracting it gives the real
        // remaining error and the aim converges onto the target instead of
        // repeatedly re-adding the full centre-to-target distance.
        state.applied_offset_x += static_cast<float>(command.move_x);
        state.applied_offset_y += static_cast<float>(command.move_y);
        command.click = click_is_due(
            lock_active,
            on_target,
            lock_elapsed_ms,
            settings.shot_delay_ms,
            shoot_active,
            state.last_click_at,
            now,
            settings.shot_interval_ms
        );
        command.send = lock_active || command.click;
        if (command.click)
        {
            state.last_click_at = now;
        }
    }
    else if (!accepted)
    {
        state.target_lock_started_at.reset();
        state.previous_aim_center.reset();
        state.filtered_target_center.reset();
        state.filtered_target_velocity = {};
        state.previous_filter_time.reset();
        state.last_click_at.reset();
        state.movement_remainder_x = 0.0F;
        state.movement_remainder_y = 0.0F;
        state.lock_smoothness_remainder_x = 0.0F;
        state.lock_smoothness_remainder_y = 0.0F;
        command.status = target_match_missing
            ? "Holding current target selection; waiting for it to reappear"
            : "Candidate ignored: below minimum confidence";
    }
    else
    {
        state.previous_aim_center.reset();
        state.filtered_target_center.reset();
        state.filtered_target_velocity = {};
        state.previous_filter_time.reset();
        state.last_click_at.reset();
        state.movement_remainder_x = 0.0F;
        state.movement_remainder_y = 0.0F;
        state.lock_smoothness_remainder_x = 0.0F;
        state.lock_smoothness_remainder_y = 0.0F;
    }

    return command;
}
} // namespace aimassist
