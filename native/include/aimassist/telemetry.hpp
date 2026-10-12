#pragma once

#include <cstdint>
#include <fstream>
#include <string>

namespace aimassist
{
struct FrameTimings
{
    double capture_ms{};
    double prepare_ms{};
    double predict_ms{};
    double result_transfer_decode_ms{};
    double postprocess_ms{};
    double preview_ms{};
    double capture_to_detection_ms{};
    double capture_to_preview_ms{};
};

class TelemetryWriter
{
public:
    explicit TelemetryWriter(std::string const& path);
    ~TelemetryWriter();

    TelemetryWriter(TelemetryWriter const&) = delete;
    TelemetryWriter& operator=(TelemetryWriter const&) = delete;

    bool ok() const noexcept;
    std::string const& path() const noexcept;
    void write(
        std::string const& timestamp_utc,
        std::uint64_t sequence,
        std::string const& model,
        std::string const& device,
        FrameTimings const& timings
    );
    void flush();

private:
    std::ofstream file_;
    std::string path_;
};
} // namespace aimassist
