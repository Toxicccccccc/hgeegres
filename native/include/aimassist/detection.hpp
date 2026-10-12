#pragma once

namespace aimassist
{
struct Vec2
{
    float x{};
    float y{};
};

struct Detection
{
    float x1{};
    float y1{};
    float x2{};
    float y2{};
    float confidence{};
    int class_id{};
};
} // namespace aimassist
