#pragma once

// Movement shaping for accessibility.
//
// Purpose: make the assisted crosshair movement smooth, bounded, and
// predictable so a player with a motor impairment can control it, and so it
// settles on the target instead of jittering around it. This is a comfort and
// controllability feature. It deliberately does NOT randomize or add noise to
// disguise automated movement -- the behavior stays deterministic and
// documentable, and it can be switched off entirely for baseline behavior.
//
// The shaper converts a desired displacement into a bounded step per frame:
//   * a per-frame speed cap, so a large correction cannot teleport the aim;
//   * acceleration limiting, so the aim ramps up and eases down instead of
//     starting and stopping abruptly;
//   * sub-pixel remainder accumulation, so small corrections are not lost to
//     integer rounding (the cause of the classic "stuck just short" jitter);
//   * a stop tolerance that snaps the final fraction of a pixel and zeroes the
//     velocity, killing the oscillation loop around the target.

#include <algorithm>
#include <cmath>

namespace aimassist
{
    struct MovementSettings
    {
        bool enabled{true};
        // Largest movement, in screen pixels, allowed in a single frame.
        float max_step_px{60.0F};
        // Fraction of the remaining speed gained per frame (0-1). Lower is gentler.
        float acceleration{0.35F};
        // Within this distance of the target the aim snaps and settles.
        float stop_tolerance_px{1.5F};
    };

    struct MovementState
    {
        float velocity_x{};
        float velocity_y{};
        float remainder_x{};
        float remainder_y{};
    };

    struct MovementOutput
    {
        int step_x{};
        int step_y{};
        bool settling{};
    };

    class MovementShaper
    {
    public:
        void set_settings(MovementSettings const &settings)
        {
            settings_ = settings;
        }

        MovementSettings const &settings() const noexcept
        {
            return settings_;
        }

        void reset()
        {
            state_ = {};
        }

        // Convert a desired displacement (current aim error, in pixels) into an
        // integer step to hand to the input backend.
        MovementOutput shape(float error_x, float error_y)
        {
            MovementOutput output;
            auto const distance = std::sqrt(error_x * error_x + error_y * error_y);

            if (distance <= settings_.stop_tolerance_px)
            {
                // Close enough: stop and clear momentum so the aim cannot orbit the
                // target. This is the anti-oscillation guarantee.
                state_ = {};
                output.settling = true;
                return output;
            }

            if (!settings_.enabled)
            {
                // Baseline behavior: apply the error directly, keeping only the
                // sub-pixel remainder so integer truncation does not lose it.
                auto const target_x = static_cast<int>(error_x + state_.remainder_x);
                auto const target_y = static_cast<int>(error_y + state_.remainder_y);
                state_.remainder_x = error_x + state_.remainder_x - static_cast<float>(target_x);
                state_.remainder_y = error_y + state_.remainder_y - static_cast<float>(target_y);
                output.step_x = target_x;
                output.step_y = target_y;
                return output;
            }

            // Desired velocity for this frame, bounded by the per-frame cap.
            auto const desired_x = std::clamp(error_x, -settings_.max_step_px, settings_.max_step_px);
            auto const desired_y = std::clamp(error_y, -settings_.max_step_px, settings_.max_step_px);

            // Ease toward the desired velocity instead of jumping to it.
            auto const gain = settings_.acceleration;
            state_.velocity_x += (desired_x - state_.velocity_x) * gain;
            state_.velocity_y += (desired_y - state_.velocity_y) * gain;

            // When the remaining distance is smaller than the current velocity,
            // clamp so the aim cannot overshoot the target.
            auto const velocity_magnitude = std::sqrt(
                state_.velocity_x * state_.velocity_x + state_.velocity_y * state_.velocity_y);
            if (velocity_magnitude > distance && velocity_magnitude > 1.0e-4F)
            {
                auto const scale = distance / velocity_magnitude;
                state_.velocity_x *= scale;
                state_.velocity_y *= scale;
            }

            // Accumulate the fractional part so slow movement still progresses.
            state_.remainder_x += state_.velocity_x;
            state_.remainder_y += state_.velocity_y;
            auto const step_x = static_cast<int>(state_.remainder_x);
            auto const step_y = static_cast<int>(state_.remainder_y);
            state_.remainder_x -= static_cast<float>(step_x);
            state_.remainder_y -= static_cast<float>(step_y);

            output.step_x = step_x;
            output.step_y = step_y;
            return output;
        }

    private:
        MovementSettings settings_{};
        MovementState state_{};
    };
} // namespace aimassist
