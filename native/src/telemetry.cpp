#include "aimassist/telemetry.hpp"

#include <iomanip>

namespace aimassist
{
TelemetryWriter::TelemetryWriter(std::string const& path)
    : path_(path)
{
    // An empty path means telemetry is switched off: no file is created at all
    // and every write becomes a no-op. This is the default.
    if (path.empty())
    {
        return;
    }
    file_.open(path, std::ios::out | std::ios::trunc);
    if (!file_)
    {
        return;
    }
    file_ << "timestamp_utc,sequence,model,device,capture_ms,prepare_ms,"
             "predict_call_ms,result_transfer_decode_ms,postprocess_ms,"
             "preview_submit_ms,capture_to_detection_ms,capture_to_preview_submit_ms\n";
}

TelemetryWriter::~TelemetryWriter()
{
    if (file_.is_open())
    {
        file_.flush();
        file_.close();
    }
}

bool TelemetryWriter::ok() const noexcept
{
    return file_.is_open() && static_cast<bool>(file_);
}

std::string const& TelemetryWriter::path() const noexcept
{
    return path_;
}

void TelemetryWriter::write(
    std::string const& timestamp_utc,
    std::uint64_t sequence,
    std::string const& model,
    std::string const& device,
    FrameTimings const& timings
)
{
    if (!file_.is_open())
    {
        return;
    }
    if (!ok())
    {
        return;
    }
    file_ << std::fixed << std::setprecision(6)
          << timestamp_utc << ','
          << sequence << ','
          << model << ','
          << device << ','
          << timings.capture_ms << ','
          << timings.prepare_ms << ','
          << timings.predict_ms << ','
          << timings.result_transfer_decode_ms << ','
          << timings.postprocess_ms << ','
          << timings.preview_ms << ','
          << timings.capture_to_detection_ms << ','
          << timings.capture_to_preview_ms << '\n';
}

void TelemetryWriter::flush()
{
    if (ok())
    {
        file_.flush();
    }
}
} // namespace aimassist
