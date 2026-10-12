// Standalone sanity test for the SigmaDrift movement generator.
//
// It verifies the properties the movement path relies on:
//   * a fresh movement reaches (approximately) the requested endpoint;
//   * every emitted step is a finite integer and the total matches the plan;
//   * a second, independent movement produces sane steps (the emitted-progress
//     bookkeeping must reset on begin_move(), or the aim stalls/snaps);
//   * an axis-aligned movement stays on that axis (the correction vector is not
//     smeared diagonally).
//
// Build: cl /std:c++20 /EHsc /I native\include native\src\sigmadrift_test.cpp

#include "aimassist/sigma_drift.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iostream>

namespace
{
    int failures = 0;

    void check(bool condition, char const *label)
    {
        std::cout << (condition ? "[ok  ] " : "[FAIL] ") << label << '\n';
        if (!condition)
        {
            ++failures;
        }
    }

    // Run one full movement at a fixed frame interval and return the total delta
    // plus how many frames it took.
    struct MoveResult
    {
        int total_x{};
        int total_y{};
        int frames{};
    };

    MoveResult run_move(aimassist::SigmaDrift &drift, int start_x, int start_y, int target_x, int target_y)
    {
        MoveResult result;
        drift.begin_move(
            static_cast<float>(start_x), static_cast<float>(start_y),
            static_cast<float>(target_x), static_cast<float>(target_y));
        for (int frame = 0; frame < 2000 && drift.active(); ++frame)
        {
            int dx = 0, dy = 0;
            drift.step(7.8, dx, dy);
            result.total_x += dx;
            result.total_y += dy;
            ++result.frames;
        }
        return result;
    }
} // namespace

int main()
{
    aimassist::SigmaDrift drift;

    // A horizontal move must land on the endpoint and never wander vertically.
    auto const horizontal = run_move(drift, 0, 0, 300, 0);
    check(horizontal.frames > 0, "horizontal move emits steps");
    check(std::abs(horizontal.total_x - 300) <= 3, "horizontal move lands on the target x");
    check(std::abs(horizontal.total_y) <= 2, "horizontal move stays on the axis (no diagonal smear)");

    // A vertical move must not pick up a horizontal component.
    auto const vertical = run_move(drift, 0, 0, 0, 300);
    check(std::abs(vertical.total_y - 300) <= 3, "vertical move lands on the target y");
    check(std::abs(vertical.total_x) <= 2, "vertical move stays on the axis");

    // A second movement must be independent of the first (this is the reset the
    // previous code was missing).
    auto const second = run_move(drift, 100, 100, 400, 100);
    check(std::abs(second.total_x - 300) <= 3, "a second movement lands correctly (progress resets)");

    // A diagonal move must reach the target on both axes.
    auto const diagonal = run_move(drift, 0, 0, 200, -150);
    check(std::abs(diagonal.total_x - 200) <= 3, "diagonal move lands on x");
    check(std::abs(diagonal.total_y + 150) <= 3, "diagonal move lands on y");

    // Degenerate: a tiny move should not spin forever.
    auto const tiny = run_move(drift, 0, 0, 0, 0);
    check(tiny.frames <= 2, "a zero-length move terminates immediately");

    if (failures == 0)
    {
        std::cout << "SigmaDrift tests passed\n";
        return 0;
    }
    std::cout << failures << " SigmaDrift check(s) FAILED\n";
    return 1;
}
