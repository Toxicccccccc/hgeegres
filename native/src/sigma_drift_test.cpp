// Tests for SigmaDrift convergence and snappiness.
//
// The engine used to plan SigmaDrift in absolute position space and never apply
// the sigmadrift_* settings, so the stroke either stalled or crawled and the
// generator looked like it "did nothing". These checks pin the behaviour that
// matters to the aim assist: the stroke must actually reach the target, and a
// higher snap must make it get there faster without losing accuracy.
#include "aimassist/sigma_drift.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace
{
void require(bool condition, char const* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

struct Result
{
    int frames{};
    int frames_to_half{};
    int final_x{};
    int final_y{};
    double error{};
};

Result run(double snap, float target_x, float target_y)
{
    aimassist::SigmaDrift drift;
    aimassist::SigmaDriftConfig config;
    config.snap = snap;
    drift.set_config(config);
    drift.begin_move(0.0F, 0.0F, target_x, target_y);

    Result result;
    int accumulated_x = 0;
    int accumulated_y = 0;
    result.frames_to_half = -1;
    auto const total = std::sqrt(static_cast<double>(target_x * target_x + target_y * target_y));
    constexpr int dt_ms = 8;
    while (drift.active() && result.frames < 400)
    {
        int step_x = 0;
        int step_y = 0;
        drift.step(static_cast<double>(dt_ms), step_x, step_y);
        accumulated_x += step_x;
        accumulated_y += step_y;
        ++result.frames;
        auto const travelled = std::sqrt(static_cast<double>(
            accumulated_x * accumulated_x + accumulated_y * accumulated_y));
        if (result.frames_to_half < 0 && travelled >= total * 0.5)
        {
            result.frames_to_half = result.frames;
        }
    }
    result.final_x = accumulated_x;
    result.final_y = accumulated_y;
    auto const dx = static_cast<double>(accumulated_x) - target_x;
    auto const dy = static_cast<double>(accumulated_y) - target_y;
    result.error = std::sqrt(dx * dx + dy * dy);
    return result;
}
} // namespace

int main()
{
    try
    {
        // The stroke must actually reach the target (within a couple of pixels)
        // rather than stalling short -- the "SigmaDrift does nothing" regression.
        auto const snappy = run(0.8, 120.0F, 40.0F);
        require(snappy.error <= 2.0, "snap=0.8 stroke must land on the target");
        require(snappy.frames > 0, "snap=0.8 stroke must actually move");

        // Snappiness: the default must reach the target far faster than the raw
        // biomechanical model, which crawled for hundreds of milliseconds.
        auto const slow = run(0.0, 120.0F, 40.0F);
        require(snappy.frames < slow.frames,
            "snap must close the gap faster than the full human model");
        // The default must get halfway quickly: aim assist cannot afford the
        // deliberate-reach lead-in the human model has.
        require(snappy.frames_to_half > 0 && snappy.frames_to_half <= 6,
            "snap=0.8 must cover half the distance within a few frames");

        // Maximum snap is the cleanest and fastest. SigmaDrift is stochastic (the
        // RNG is seeded from random_device), so the bound has to tolerate the odd
        // single-pixel rounding, not demand an exact landing; two pixels is well
        // inside a head-sized box.
        auto const instant = run(1.0, 120.0F, 40.0F);
        require(instant.error <= 2.0, "snap=1.0 stroke must land on the target");
        require(instant.frames <= snappy.frames,
            "snap=1.0 must not be slower than snap=0.8");

        // Accuracy is not traded for speed: the fast strokes must not overshoot
        // the target by more than a pixel or two.
        require(std::abs(instant.final_x - 120) <= 2, "snap=1.0 must not overshoot x");
        require(std::abs(instant.final_y - 40) <= 2, "snap=1.0 must not overshoot y");

        // A tiny final correction must still terminate cleanly.
        auto const tiny = run(0.8, 3.0F, 2.0F);
        require(tiny.error <= 2.0, "small moves must also converge");

        std::cout << "sigma drift tests passed\n";
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "sigma drift tests failed: " << error.what() << '\n';
        return 1;
    }
}
