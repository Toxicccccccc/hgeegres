#pragma once

// Target position/velocity estimator, adapted for this project from the
// constant-acceleration-free 2D Kalman filter used by the sunone_aimbot_2
// reference (aim_kalman.h). It keeps that reference's structure and defaults
// but speaks this project's Vec2 container so targeting can use it directly.
//
// The filter tracks one screen-space point per axis (position + velocity) and
// exposes a damped look-ahead prediction. Prediction is only meaningful after a
// short warmup, which prevents a single noisy first observation from producing a
// large lead.

#include "aimassist/detection.hpp"

#include <algorithm>
#include <cmath>

namespace aimassist
{
struct KalmanSettings
{
    bool enabled{true};
    // Process/measurement noise follow the reference defaults, which were tuned
    // for 320-640px detection crops at hundreds of frames per second.
    double process_noise_position{40.0};
    double process_noise_velocity{1800.0};
    double measurement_noise{35.0};
    // Exponential velocity decay so a stopped target stops being led quickly.
    double velocity_damping{0.08};
    double max_velocity{20000.0};
    int warmup_frames{2};
};

struct KalmanTelemetry
{
    bool initialized{false};
    bool enabled{true};
    bool predicting{false};
    int warmup_remaining{0};
    Vec2 measurement{};
    Vec2 estimate{};
    Vec2 predicted{};
    Vec2 velocity{};
};

class Kalman2D
{
public:
    void set_settings(KalmanSettings const& settings)
    {
        settings_ = clamp_settings(settings);
        warmup_remaining_ = std::clamp(warmup_remaining_, 0, settings_.warmup_frames);
    }

    KalmanSettings const& settings() const noexcept
    {
        return settings_;
    }

    void reset()
    {
        x_axis_ = AxisState{};
        y_axis_ = AxisState{};
        initialized_ = false;
        warmup_remaining_ = settings_.warmup_frames;
        last_measurement_ = {};
    }

    bool initialized() const noexcept
    {
        return initialized_;
    }

    Vec2 position() const noexcept
    {
        return {static_cast<float>(x_axis_.position), static_cast<float>(y_axis_.position)};
    }

    Vec2 velocity() const noexcept
    {
        return {static_cast<float>(x_axis_.velocity), static_cast<float>(y_axis_.velocity)};
    }

    // Damped extrapolation of the current estimate `lookahead_seconds` ahead.
    Vec2 predict(double lookahead_seconds) const
    {
        if (!initialized_)
        {
            return {};
        }
        auto const lookahead = std::clamp(lookahead_seconds, 0.0, max_lookahead_seconds);
        if (lookahead <= 0.0 || warmup_remaining_ > 0)
        {
            return position();
        }
        return {
            static_cast<float>(predict_axis(x_axis_, settings_.velocity_damping, lookahead)),
            static_cast<float>(predict_axis(y_axis_, settings_.velocity_damping, lookahead))
        };
    }

    // Feed one observation. `delta_seconds` is the time since the previous
    // observation and `lookahead_seconds` the desired prediction horizon.
    KalmanTelemetry update(Vec2 measurement, double delta_seconds, double lookahead_seconds)
    {
        auto const dt = std::clamp(delta_seconds, 1.0e-4, 0.25);
        auto const lookahead = std::clamp(lookahead_seconds, 0.0, max_lookahead_seconds);

        if (!initialized_)
        {
            initialize(measurement);
            return build_telemetry(measurement, lookahead);
        }

        if (!settings_.enabled)
        {
            // Pass-through mode: no filtering, finite-difference velocity only.
            auto const previous = position();
            auto const velocity = Vec2{
                static_cast<float>(clamp_abs(
                    static_cast<double>(measurement.x - previous.x) / dt,
                    settings_.max_velocity
                )),
                static_cast<float>(clamp_abs(
                    static_cast<double>(measurement.y - previous.y) / dt,
                    settings_.max_velocity
                ))
            };
            x_axis_.position = measurement.x;
            y_axis_.position = measurement.y;
            x_axis_.velocity = velocity.x;
            y_axis_.velocity = velocity.y;
            last_measurement_ = measurement;
            return build_telemetry(measurement, lookahead);
        }

        update_axis(x_axis_, measurement.x, dt);
        update_axis(y_axis_, measurement.y, dt);
        last_measurement_ = measurement;

        return build_telemetry(measurement, lookahead);
    }

private:
    static constexpr double max_lookahead_seconds = 1.5;

    struct AxisState
    {
        double position{};
        double velocity{};
        double p00{150.0};
        double p01{};
        double p10{};
        double p11{700.0};
    };

    static KalmanSettings clamp_settings(KalmanSettings const& input)
    {
        KalmanSettings output = input;
        output.process_noise_position = std::clamp(output.process_noise_position, 1.0e-4, 5000.0);
        output.process_noise_velocity = std::clamp(output.process_noise_velocity, 1.0e-4, 50000.0);
        output.measurement_noise = std::clamp(output.measurement_noise, 1.0e-4, 5000.0);
        output.velocity_damping = std::clamp(output.velocity_damping, 0.0, 3.0);
        output.max_velocity = std::clamp(output.max_velocity, 100.0, 60000.0);
        output.warmup_frames = std::clamp(output.warmup_frames, 0, 20);
        return output;
    }

    static double clamp_abs(double value, double max_abs)
    {
        return std::clamp(value, -max_abs, max_abs);
    }

    static double predict_axis(AxisState const& axis, double damping, double lookahead)
    {
        if (lookahead <= 0.0)
        {
            return axis.position;
        }
        if (damping <= 1.0e-6)
        {
            return axis.position + axis.velocity * lookahead;
        }
        auto const decay = std::exp(-damping * lookahead);
        return axis.position + axis.velocity * (1.0 - decay) / damping;
    }

    void initialize(Vec2 measurement)
    {
        x_axis_.position = measurement.x;
        y_axis_.position = measurement.y;
        x_axis_.velocity = 0.0;
        y_axis_.velocity = 0.0;
        x_axis_.p00 = settings_.measurement_noise;
        y_axis_.p00 = settings_.measurement_noise;
        x_axis_.p11 = settings_.process_noise_velocity;
        y_axis_.p11 = settings_.process_noise_velocity;
        x_axis_.p01 = x_axis_.p10 = 0.0;
        y_axis_.p01 = y_axis_.p10 = 0.0;
        warmup_remaining_ = settings_.warmup_frames;
        initialized_ = true;
        last_measurement_ = measurement;
    }

    double update_axis(AxisState& axis, double measurement, double dt)
    {
        auto const damping_factor = std::exp(-settings_.velocity_damping * dt);
        axis.position += axis.velocity * dt;
        axis.velocity *= damping_factor;

        auto const old_p00 = axis.p00;
        auto const old_p01 = axis.p01;
        auto const old_p10 = axis.p10;
        auto const old_p11 = axis.p11;

        axis.p00 = old_p00 + dt * (old_p01 + old_p10 + dt * old_p11)
            + settings_.process_noise_position * dt;
        axis.p01 = old_p01 + dt * old_p11;
        axis.p10 = old_p10 + dt * old_p11;
        axis.p11 = old_p11 + settings_.process_noise_velocity * dt;

        auto const innovation = measurement - axis.position;
        auto const s = std::max(1.0e-9, axis.p00 + settings_.measurement_noise);
        auto const k0 = axis.p00 / s;
        auto const k1 = axis.p10 / s;

        axis.position += k0 * innovation;
        axis.velocity += k1 * innovation;
        axis.velocity = clamp_abs(axis.velocity, settings_.max_velocity);

        auto const p00 = axis.p00;
        auto const p01 = axis.p01;
        auto const p10 = axis.p10;
        auto const p11 = axis.p11;

        axis.p00 = std::max(1.0e-9, (1.0 - k0) * p00);
        axis.p01 = (1.0 - k0) * p01;
        axis.p10 = p10 - k1 * p00;
        axis.p11 = std::max(1.0e-9, p11 - k1 * p01);

        return innovation;
    }

    KalmanTelemetry build_telemetry(Vec2 measurement, double lookahead_seconds)
    {
        KalmanTelemetry telemetry;
        telemetry.initialized = initialized_;
        telemetry.enabled = settings_.enabled;
        telemetry.warmup_remaining = warmup_remaining_;
        telemetry.measurement = measurement;
        telemetry.estimate = position();
        telemetry.velocity = velocity();

        if (warmup_remaining_ > 0)
        {
            --warmup_remaining_;
            telemetry.predicted = position();
            telemetry.predicting = false;
            telemetry.warmup_remaining = warmup_remaining_;
            return telemetry;
        }

        telemetry.predicted = predict(lookahead_seconds);
        telemetry.predicting = lookahead_seconds > 0.0;
        return telemetry;
    }

    KalmanSettings settings_{};
    AxisState x_axis_{};
    AxisState y_axis_{};
    bool initialized_{};
    int warmup_remaining_{};
    Vec2 last_measurement_{};
};
} // namespace aimassist
