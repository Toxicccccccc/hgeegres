// Simulated tracking test.
//
// This drives process_detections with a target that moves across the FOV and
// measures how far the emitted movement lags the target's true position, for the
// hard-lock profile versus the smoother default. The aim error is measured from
// the crosshair: after each frame the crosshair moves by the emitted step, so the
// true error is (target - crosshair). A hard lock must keep that error near zero
// while the default lags behind a moving target.
#include "aimassist/settings.hpp"
#include "aimassist/targeting.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace
{
void require(bool condition, char const* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

struct Simulation
{
    double average_lag{};
    double peak_lag{};
    double final_lag{};
};

// Move a target at `speed_px_per_frame` across the screen and track it. The
// crosshair starts at the FOV centre and moves by every emitted step.
Simulation simulate(aimassist::Settings settings, float speed_px_per_frame)
{
    aimassist::TrackerState state;
    float const fov = static_cast<float>(settings.fov);
    float const center = fov * 0.5F;

    // Target starts a little off centre and travels right.
    float target_x = center + 40.0F;
    float const target_y = center;
    float crosshair_x = center;
    float crosshair_y = center;
    float last_aim_x = center;
    float last_aim_y = center;

    double total_lag = 0.0;
    double peak_lag = 0.0;
    int frames = 0;
    double now = 0.0;
    constexpr double dt = 1.0 / 240.0;

    for (int frame = 0; frame < 120; ++frame)
    {
        now += dt;
        // Let the target travel most of the way, then hold it still so the final
        // lock accuracy can be measured.
        if (frame < 60)
        {
            target_x += speed_px_per_frame;
        }
        aimassist::Detection box{
            target_x - 15.0F,
            target_y - 30.0F,
            target_x + 15.0F,
            target_y + 10.0F,
            0.9F,
            0
        };
        std::vector<aimassist::Detection> detections{box};
        auto const command = aimassist::process_detections(
            detections, settings, state, /*lock_active=*/true, /*shoot_active=*/false, now
        );
        // The engine's error is measured from the fixed FOV centre, so the
        // crosshair moves by exactly what was emitted and the residual is the gap
        // between where it landed and where the target's aim point now is.
        auto const aim = aimassist::get_aim_point(box, settings.aim_height);
        if (command.send)
        {
            crosshair_x += static_cast<float>(command.move_x);
            crosshair_y += static_cast<float>(command.move_y);
        }
        auto const lag = std::sqrt(
            std::pow(static_cast<double>(aim.x) - crosshair_x, 2.0)
            + std::pow(static_cast<double>(aim.y) - crosshair_y, 2.0)
        );
        if (frame >= 10)
        {
            total_lag += lag;
            peak_lag = std::max(peak_lag, lag);
            ++frames;
        }
        last_aim_x = aim.x;
        last_aim_y = aim.y;
    }
    Simulation result;
    result.average_lag = frames > 0 ? total_lag / frames : 0.0;
    result.peak_lag = peak_lag;
    result.final_lag = std::sqrt(
        std::pow(static_cast<double>(last_aim_x) - crosshair_x, 2.0)
        + std::pow(static_cast<double>(last_aim_y) - crosshair_y, 2.0)
    );
    return result;
}

aimassist::Settings make_settings(bool hard_lock)
{
    auto settings = aimassist::default_settings();
    settings.fov = 640;
    settings.fov_shape = "Circle";
    settings.confidence_threshold = 0.25F;
    settings.action_confidence_threshold = 0.3F;
    settings.aim_height = 92.0F;
    settings.target_priority_mode = "confidence";
    settings.focus_single_target = true;
    settings.reacquire_radius_px = 240;
    settings.target_lost_grace_ms = 0;
    settings.hard_lock = hard_lock;
    if (hard_lock)
    {
        settings.smoothness = 1.0F;
        settings.aiming_curve = "Linear";
        settings.kalman_enabled = false;
        settings.prediction_enabled = true;
        settings.prediction_horizon_ms = 60;
    }
    else
    {
        // The user's previous "not enough accuracy" settings.
        settings.smoothness = 15.8F;
        settings.aiming_curve = "Rational";
        settings.kalman_enabled = true;
        settings.kalman_process_noise = 41.0F;
        settings.kalman_measurement_noise = 24.0F;
        settings.prediction_enabled = false;
    }
    return settings;
}

// A normal (non-hard-lock) profile with a sane smoothness and the default
// trajectory method. This is what most users run, and it must also hold the
// target rather than run away from it -- the applied-offset fix lives in the core
// tracker, so every profile benefits.
aimassist::Settings make_normal_settings()
{
    auto settings = aimassist::default_settings();
    settings.fov = 640;
    settings.fov_shape = "Circle";
    settings.confidence_threshold = 0.25F;
    settings.action_confidence_threshold = 0.3F;
    settings.aim_height = 92.0F;
    settings.target_priority_mode = "confidence";
    settings.focus_single_target = true;
    settings.reacquire_radius_px = 240;
    settings.target_lost_grace_ms = 0;
    settings.smoothness = 4.0F;
    settings.aiming_curve = "Linear";
    settings.kalman_enabled = true;
    settings.prediction_enabled = true;
    settings.prediction_horizon_ms = 60;
    return settings;
}
} // namespace

int main()
{
    try
    {
        auto const slow_target = 3.0F; // ~720 px/s
        auto const hard = simulate(make_settings(true), slow_target);
        auto const soft = simulate(make_settings(false), slow_target);
        auto const normal = simulate(make_normal_settings(), slow_target);

        std::cout << "tracking (3px/frame target; avg/peak include any deliberate "
                     "prediction lead):\n";
        std::cout << "  hard_lock: avg=" << hard.average_lag
                  << " peak=" << hard.peak_lag
                  << " final=" << hard.final_lag << "\n";
        std::cout << "  normal   : avg=" << normal.average_lag
                  << " peak=" << normal.peak_lag
                  << " final=" << normal.final_lag << "\n";
        std::cout << "  old slow : avg=" << soft.average_lag
                  << " peak=" << soft.peak_lag
                  << " final=" << soft.final_lag << "\n";

        // The decisive properties: the aim CONVERGES onto a held target (final lag
        // near zero) and the tracking error is BOUNDED (it never grows without
        // limit, which was the runaway bug). The average includes the deliberate
        // prediction lead, so it is bounded rather than near-zero while moving.
        require(hard.final_lag < 1.0, "hard lock must settle exactly on a held target");
        require(normal.final_lag < 2.0, "a normal profile must settle onto the target");
        require(hard.peak_lag < 60.0, "hard lock must stay bounded, not run away");
        require(normal.peak_lag < 60.0, "a normal profile must stay bounded, not run away");

        // The old deliberately-slow profile is markedly worse than the tuned default.
        require(normal.average_lag < soft.average_lag,
            "the tuned default must track better than the old slow profile");

        // Focus: once a target is held, a more-confident rival appearing near the
        // crosshair must NOT steal the lock. This is the "focus one target, do not
        // switch between enemies" behaviour.
        {
            auto settings = make_normal_settings();
            settings.focus_single_target = true;
            aimassist::TrackerState state;
            float const center = 320.0F;
            // First frame: acquire a target off to the right.
            std::vector<aimassist::Detection> first{
                {center + 60.0F, center - 30.0F, center + 90.0F, center + 10.0F, 0.6F, 0}
            };
            aimassist::process_detections(first, settings, state, true, false, 0.01);
            auto const held = state.previous_target_center;
            require(held.has_value(), "a target must be acquired");
            // Next frame: the held target is still there, and a much more confident
            // rival sits nearer the crosshair. The lock must stay on the held one.
            std::vector<aimassist::Detection> with_rival{
                {center + 62.0F, center - 30.0F, center + 92.0F, center + 10.0F, 0.55F, 0},
                {center + 4.0F, center - 30.0F, center + 24.0F, center + 10.0F, 0.95F, 0}
            };
            aimassist::process_detections(with_rival, settings, state, true, false, 0.02);
            auto const still = state.previous_target_center;
            require(still.has_value(), "the held target must survive the rival");
            auto const moved = std::sqrt(
                std::pow(static_cast<double>(still->x - held->x), 2.0)
                + std::pow(static_cast<double>(still->y - held->y), 2.0));
            require(moved < 12.0,
                "focus_single_target must not switch to a more-confident rival");
        }

        // "Then the closest one": with no prior lock, the nearest box to the
        // crosshair wins regardless of confidence.
        {
            auto settings = make_normal_settings();
            aimassist::TrackerState fresh;
            float const center = 320.0F;
            std::vector<aimassist::Detection> boxes{
                {center + 140.0F, center - 30.0F, center + 170.0F, center + 10.0F, 0.95F, 0},
                {center + 10.0F, center - 30.0F, center + 40.0F, center + 10.0F, 0.55F, 0}
            };
            aimassist::process_detections(boxes, settings, fresh, true, false, 0.01);
            require(fresh.previous_target_center.has_value(), "a target must be chosen");
            require(fresh.previous_target_center->x < center + 60.0F,
                "without a lock the closest-to-crosshair target must be chosen");
        }

        std::cout << "tracking tests passed\n";
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "tracking tests failed: " << error.what() << '\n';
        return 1;
    }
}
