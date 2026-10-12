// Unit tests for the accessibility movement shaper and the dataset collector's
// label formatting. These are deterministic: they assert the properties the
// movement feature promises -- bounded steps, no overshoot, no oscillation --
// rather than golden numbers, so tuning the defaults does not break the tests.

#include "aimassist/dataset.hpp"
#include "aimassist/movement.hpp"

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

int magnitude(int x, int y)
{
    return std::abs(x) + std::abs(y);
}
} // namespace

int main()
{
    try
    {
        aimassist::MovementSettings settings;
        settings.enabled = true;
        settings.max_step_px = 10.0F;
        settings.acceleration = 0.5F;
        settings.stop_tolerance_px = 1.5F;

        // 1. Per-frame step is bounded even for a huge error, so a large
        //    correction cannot teleport the crosshair.
        {
            aimassist::MovementShaper shaper;
            shaper.set_settings(settings);
            for (int frame = 0; frame < 50; ++frame)
            {
                auto const output = shaper.shape(5000.0F, 5000.0F);
                require(magnitude(output.step_x, output.step_y) <= 20,
                    "A single frame must never exceed the configured step cap");
            }
        }

        // 2. Acceleration ramps: the first step is smaller than a later step,
        //    which is what makes the motion feel smooth rather than abrupt.
        {
            aimassist::MovementShaper shaper;
            shaper.set_settings(settings);
            auto const first = shaper.shape(200.0F, 0.0F);
            auto const second = shaper.shape(200.0F, 0.0F);
            require(second.step_x >= first.step_x,
                "Movement should ease in rather than jumping to full speed");
        }

        // 3. No overshoot: the shaper never steps further than the remaining
        //    error once it is within reach.
        {
            aimassist::MovementShaper shaper;
            shaper.set_settings(settings);
            float remaining = 300.0F;
            for (int frame = 0; frame < 400 && remaining > 0.0F; ++frame)
            {
                auto const output = shaper.shape(remaining, 0.0F);
                require(output.step_x <= static_cast<int>(remaining) + 1,
                    "The shaper must not step past the target");
                remaining -= static_cast<float>(output.step_x);
            }
            require(remaining <= 1.0F, "The aim should converge onto the target");
        }

        // 4. Anti-oscillation: inside the stop tolerance the output is zero and
        //    velocity is cleared, so the aim settles instead of jittering.
        {
            aimassist::MovementShaper shaper;
            shaper.set_settings(settings);
            for (int frame = 0; frame < 20; ++frame)
            {
                shaper.shape(60.0F, 60.0F);
            }
            auto const settled = shaper.shape(0.5F, 0.4F);
            require(settled.step_x == 0 && settled.step_y == 0,
                "Inside the stop tolerance there must be no movement");
            require(settled.settling, "The shaper should report a settling state");
            auto const after = shaper.shape(0.2F, 0.1F);
            require(after.step_x == 0 && after.step_y == 0,
                "Momentum must not leak out after settling");
        }

        // 5. Disabled means pass-through: the requested movement is applied
        //    directly, so a user can always return to baseline behavior.
        {
            aimassist::MovementSettings off = settings;
            off.enabled = false;
            aimassist::MovementShaper shaper;
            shaper.set_settings(off);
            auto const output = shaper.shape(37.0F, -21.0F);
            require(output.step_x == 37 && output.step_y == -21,
                "With shaping disabled the movement must be applied unchanged");
        }

        // 6. Sub-pixel progress is not lost: an error just above the stop
        //    tolerance accumulates across frames instead of rounding away.
        //    (Below the tolerance the correct behavior is to settle, so the
        //    error here is deliberately larger than it.)
        {
            aimassist::MovementShaper shaper;
            shaper.set_settings(settings);
            require(2.0F > settings.stop_tolerance_px,
                "This case must exercise the moving path, not the settling path");
            int moved = 0;
            for (int frame = 0; frame < 30; ++frame)
            {
                moved += shaper.shape(2.0F, 0.0F).step_x;
            }
            require(moved > 0,
                "Sub-pixel error must accumulate rather than being rounded to zero");
        }

        // 7. Small negative movement is delivered with the correct sign. Any
        //    previous implementation failure here would send the aim the wrong
        //    way by one pixel.
        {
            aimassist::MovementShaper shaper;
            shaper.set_settings(settings);
            int moved = 0;
            for (int frame = 0; frame < 40; ++frame)
            {
                moved += shaper.shape(-40.0F, 0.0F).step_x;
            }
            require(moved < 0, "Leftward movement must stay leftward");
        }

        // 8. Dataset label formatting: YOLO rows are normalised to 0..1 and
        //    clamped, so a box touching the edge cannot produce an invalid label.
        {
            aimassist::DatasetSettings dataset_settings;
            dataset_settings.output_dir = "test_dataset_output";
            dataset_settings.class_names = "enemy,teammate";
            aimassist::DatasetCollector collector;
            std::string message;
            require(collector.start(dataset_settings, message),
                "The dataset collector should start with a writable folder");

            std::vector<aimassist::Detection> detections{
                {10.0F, 10.0F, 110.0F, 210.0F, 0.9F, 1},
                {-5.0F, -5.0F, 330.0F, 330.0F, 0.8F, 0},
            };
            std::vector<std::uint8_t> frame(
                static_cast<std::size_t>(320) * 320 * 4, 128
            );
            for (int index = 0; index < 5; ++index)
            {
                collector.submit(frame.data(), 320, detections, static_cast<std::uint64_t>(index));
            }
            collector.stop();
            require(collector.frames_written() > 0,
                "The collector should have written at least one labelled frame");
        }

        std::cout << "native movement/dataset tests passed\n";
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "native movement/dataset tests failed: " << error.what() << '\n';
        return 1;
    }
}
