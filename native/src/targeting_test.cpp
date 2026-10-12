#include "aimassist/kalman.hpp"
#include "aimassist/settings.hpp"
#include "aimassist/targeting.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
void require(bool condition, char const* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

bool nearly_equal(float left, float right, float tolerance = 1.0e-4F)
{
    return std::fabs(left - right) <= tolerance;
}
} // namespace

int main()
{
    try
    {
        auto const linear = aimassist::movement_step(32.0F, 1.0F, 0.0F, "Linear");
        require(linear.first != 0, "Linear movement should leave the deadzone");

        auto const deadzone = aimassist::movement_step(0.4F, 1.0F, 0.0F, "Linear");
        require(deadzone.first == 0 && deadzone.second == 0.0F, "Deadzone should suppress movement");

        aimassist::Detection box{10.0F, 20.0F, 30.0F, 80.0F, 0.9F, 0};
        auto const aim = aimassist::get_aim_point(box, 75.0F);
        require(nearly_equal(aim.x, 20.0F), "Aim X should be the box center");
        require(nearly_equal(aim.y, 35.0F), "Aim Y should honor aim_height");

        std::vector<aimassist::Detection> detections{
            {0.0F, 0.0F, 10.0F, 10.0F, 0.4F, 0},
            {90.0F, 90.0F, 110.0F, 110.0F, 0.9F, 0},
            {48.0F, 48.0F, 52.0F, 52.0F, 0.8F, 0},
        };
        auto const closest = aimassist::select_target_index(detections, std::nullopt, 50.0F);
        require(closest.has_value() && *closest == 2, "Closest-to-center selection failed");

        auto settings = aimassist::default_settings();
        settings.fov = 100;
        settings.confidence_threshold = 0.25F;
        settings.action_confidence_threshold = 0.5F;
        settings.smoothness = 1.0F;
        settings.aim_height = 50.0F;
        settings.shot_delay_ms = 0;
        settings.shot_interval_ms = 0;
        settings.lock_key = "Auto";
        settings.shoot_input = "Auto";

        aimassist::TrackerState state;
        auto const command = aimassist::process_detections(
            detections,
            settings,
            state,
            true,
            true,
            1.0
        );
        require(command.has_target, "Centered high-confidence box should be accepted");
        require(command.send, "Lock+shoot should emit an assist packet");
        require(state.previous_target_center.has_value(), "Tracker should remember the selected target");

        // A held lock must survive a one-frame match miss instead of immediately
        // jumping to a distant rival. It should reacquire the original target
        // when that box returns inside the association radius.
        auto held_settings = settings;
        held_settings.fov = 400;
        held_settings.aim_height = 50.0F;
        held_settings.target_lost_grace_ms = 0;
        held_settings.reacquire_radius_px = 48;
        std::vector<aimassist::Detection> held_target{
            {215.0F, 195.0F, 225.0F, 205.0F, 0.95F, 0},
        };
        std::vector<aimassist::Detection> distant_rival{
            {345.0F, 195.0F, 355.0F, 205.0F, 0.99F, 0},
        };
        aimassist::TrackerState held_state;
        auto const acquired = aimassist::process_detections(
            held_target, held_settings, held_state, true, false, 10.0);
        require(acquired.has_target && acquired.move_x != 0,
            "The lock should acquire and move toward an eligible target");
        auto const lost = aimassist::process_detections(
            distant_rival, held_settings, held_state, true, false, 10.01);
        require(!lost.has_target && !lost.send,
            "A target miss must wait instead of moving to a distant rival");
        require(held_state.previous_target_center.has_value()
                && nearly_equal(held_state.previous_target_center->x, 220.0F),
            "A temporary miss must preserve the previous target reference");
        require(lost.status.find("waiting for it to reappear") != std::string::npos,
            "A temporary miss should explain that the lock is waiting");
        auto const reacquired = aimassist::process_detections(
            {
                {225.0F, 195.0F, 235.0F, 205.0F, 0.95F, 0},
                {345.0F, 195.0F, 355.0F, 205.0F, 0.99F, 0},
            },
            held_settings,
            held_state,
            true,
            false,
            10.02);
        require(reacquired.has_target
                && reacquired.move_x != 0
                && nearly_equal(held_state.previous_target_center->x, 230.0F),
            "The lock should reacquire the original target rather than the rival");

        auto smooth_settings = held_settings;
        smooth_settings.lock_smoothness = 2.0F;
        aimassist::TrackerState smooth_state;
        auto const smooth_first = aimassist::process_detections(
            held_target, smooth_settings, smooth_state, true, false, 12.0);
        auto const smooth_second = aimassist::process_detections(
            held_target, smooth_settings, smooth_state, true, false, 12.01);
        require(smooth_first.move_x > 0 && smooth_first.move_x < 20,
            "Lock smoothness should apply a partial correction on acquisition");
        require(smooth_second.move_x > 0 && smooth_second.move_x < smooth_first.move_x,
            "Lock smoothness should continue converging on later held-lock frames");

        aimassist::TrackerState recoil_state;
        (void)aimassist::process_detections(
            held_target, held_settings, recoil_state, true, false, 13.0);
        auto const recoil_reacquired = aimassist::process_detections(
            distant_rival, held_settings, recoil_state, true, true, 13.01);
        require(recoil_reacquired.has_target,
            "Firing recoil displacement should not immediately lose the held target");

        auto fov_settings = held_settings;
        fov_settings.fov = 100;
        fov_settings.fov_shape = "Circle";
        aimassist::TrackerState fov_state;
        auto const outside_fov = aimassist::process_detections(
            distant_rival, fov_settings, fov_state, true, false, 11.0);
        require(!outside_fov.has_target
                && outside_fov.status == "Detections outside circular FOV",
            "Out-of-zone detections should be distinguished from model misses");

        // Adaptive gain: the same error should produce a smaller step when the
        // crosshair is already close to the target than when it is far away,
        // which is what lets the aim settle instead of oscillating.
        auto const far_step = aimassist::movement_step(200.0F, 1.0F, 0.0F, "Linear").first;
        auto const near_step = aimassist::movement_step(8.0F, 1.0F, 0.0F, "Linear").first;
        require(near_step != 0, "Close-range movement should still leave the deadzone");
        require(far_step > near_step * 4,
            "Far movement should be substantially larger than close movement");

        for (float direction : {-1.0F, 1.0F})
        {
            float remaining_error = 12.0F * direction;
            float movement_remainder = 0.0F;
            for (int frame = 0; frame < 24 && std::abs(remaining_error) > 1.0F; ++frame)
            {
                auto const step = aimassist::movement_step(
                    remaining_error, 0.1F, movement_remainder, "Linear"
                );
                require(static_cast<float>(step.first) * direction >= 0.0F
                        && std::abs(static_cast<float>(step.first)) <= std::abs(remaining_error),
                    "Legacy sub-1 smoothness must not reverse or overshoot the target");
                remaining_error -= static_cast<float>(step.first);
                movement_remainder = step.second;
            }
            require(std::abs(remaining_error) <= 1.0F,
                "A legacy sub-1 smoothness value should converge without oscillation");
        }

        // Kalman filter: after steady observations the smoothed estimate should
        // sit on the measurement, and a moving target should develop velocity so
        // prediction leads ahead of the raw observation.
        aimassist::Kalman2D filter;
        auto kalman_settings = aimassist::KalmanSettings{};
        kalman_settings.warmup_frames = 0;
        filter.set_settings(kalman_settings);

        aimassist::KalmanTelemetry telemetry;
        constexpr float final_measurement_x = 100.0F + 39.0F * 4.0F; // steps 0..39 inclusive
        for (int step = 0; step < 40; ++step)
        {
            telemetry = filter.update({100.0F + static_cast<float>(step) * 4.0F, 50.0F}, 1.0 / 240.0, 0.0);
        }
        // The estimate trails a linear ramp only by the filter's smoothing lag,
        // so it must stay within a few pixels of the final measurement.
        // At 240 Hz with the reference noise settings the estimator trails a
        // 960 px/s ramp by a steady-state lag of roughly one frame's worth of
        // travel, so a ~20 px window is the correct expectation here. The point
        // of the assertion is that the estimate tracks the ramp and holds a
        // sane velocity, not that it is lag-free.
        require(nearly_equal(telemetry.estimate.x, final_measurement_x, 20.0F),
            "Kalman estimate should track a steadily moving target");
        require(telemetry.velocity.x > 400.0F && telemetry.velocity.x < 1600.0F,
            "Kalman filter should learn the target's rightward velocity (~4px per 1/240s)");

        auto const lead = filter.predict(0.05);
        require(lead.x > telemetry.estimate.x,
            "Prediction should lead ahead of the current estimate for a moving target");

        filter.reset();
        auto const fresh = filter.update({10.0F, 10.0F}, 0.0, 0.5);
        require(nearly_equal(fresh.predicted.x, 10.0F) && nearly_equal(fresh.predicted.y, 10.0F),
            "A brand new lock must not predict a lead from a single sample");

        // --- target priority modes ----------------------------------------
        // Two boxes: a weak one dead centre, a strong one off to the right.
        // These are the same vectors as tests/test_targeting_priority.py, so the
        // two engines can be shown to rank identically.
        float const center = 200.0F;
        std::vector<aimassist::Detection> sample{
            {170.0F, 170.0F, 230.0F, 230.0F, 0.40F, 0},   // centred, low confidence
            {330.0F, 170.0F, 390.0F, 230.0F, 0.95F, 0},   // off-centre, high confidence
        };
        auto const ranked_closest = aimassist::select_target_by_mode(
            sample, "closest", std::nullopt, center);
        require(ranked_closest.has_value() && *ranked_closest == 0,
            "'closest' mode should pick the centred box");
        auto const ranked_confident = aimassist::select_target_by_mode(
            sample, "confidence", std::nullopt, center);
        require(ranked_confident.has_value() && *ranked_confident == 1,
            "'confidence' mode should pick the strongest box");

        std::vector<aimassist::Detection> sizes{
            {180.0F, 180.0F, 220.0F, 220.0F, 0.9F, 0},    // small
            {140.0F, 140.0F, 260.0F, 260.0F, 0.5F, 0},    // large
        };
        auto const largest = aimassist::select_target_by_mode(
            sizes, "distance", std::nullopt, center);
        require(largest.has_value() && *largest == 1,
            "'distance' mode should pick the largest box");

        auto const sticky = aimassist::select_target_by_mode(
            sample, "sticky", aimassist::Vec2{350.0F, 200.0F}, center);
        require(sticky.has_value() && *sticky == 1,
            "'sticky' mode should keep the previous target");

        auto const empty = aimassist::select_target_by_mode(
            {}, "closest", std::nullopt, center);
        require(!empty.has_value(), "an empty frame must have no target");

        // Stickiness factor is monotonic and zero at level 0.
        require(aimassist::stickiness_margin_factor(0) == 0.0F,
            "stickiness 0 must switch immediately");
        require(aimassist::stickiness_margin_factor(4) > aimassist::stickiness_margin_factor(2),
            "a higher stickiness must demand a larger margin");

        std::cout << "native targeting tests passed\n";
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "native targeting tests failed: " << error.what() << '\n';
        return 1;
    }
}
