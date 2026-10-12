#include "aimassist/tensorrt_yolo.hpp"

#include <algorithm>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
double percentile(std::vector<double> values, double quantile)
{
    if (values.empty())
    {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    auto const index = static_cast<std::size_t>(
        quantile * static_cast<double>(values.size() - 1)
    );
    return values[index];
}

void print_timing(char const* label, std::vector<double> const& values)
{
    auto const average = std::accumulate(values.begin(), values.end(), 0.0)
        / static_cast<double>(values.size());
    std::cout << label << " ms: median=" << percentile(values, 0.50)
              << " p95=" << percentile(values, 0.95)
              << " mean=" << average << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        if (argc < 2 || argc > 4)
        {
            std::cerr << "Usage: native_engine_infer_probe <model.engine> [width height]\n";
            return 2;
        }

        auto const width = argc >= 3 ? std::stoi(argv[2]) : 437;
        auto const height = argc >= 4 ? std::stoi(argv[3]) : width;
        if (width <= 0 || height <= 0)
        {
            throw std::invalid_argument("Frame dimensions must be positive.");
        }

        aimassist::TensorRtYolo model(argv[1]);
        std::vector<std::uint8_t> frame(
            static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4,
            0
        );
        for (std::size_t index = 3; index < frame.size(); index += 4)
        {
            frame[index] = 255;
        }

        std::cout << "TensorRT input: " << model.input_width() << 'x' << model.input_height()
                  << ", classes=" << model.class_count() << '\n';
        constexpr int warmup_runs = 10;
        constexpr int measured_runs = 100;
        for (int index = 0; index < warmup_runs; ++index)
        {
            static_cast<void>(model.infer(frame.data(), width, height, 0.25F));
        }

        std::vector<double> preprocess_times;
        std::vector<double> inference_times;
        std::vector<double> result_copy_times;
        preprocess_times.reserve(measured_runs);
        inference_times.reserve(measured_runs);
        result_copy_times.reserve(measured_runs);
        std::size_t detection_count = 0;

        for (int index = 0; index < measured_runs; ++index)
        {
            auto const result = model.infer(frame.data(), width, height, 0.25F);
            preprocess_times.push_back(result.timings.upload_preprocess_ms);
            inference_times.push_back(result.timings.predict_ms);
            result_copy_times.push_back(result.timings.result_copy_ms);
            detection_count += result.detections.size();
        }

        std::cout << std::fixed << std::setprecision(3);
        print_timing("CUDA upload + preprocess", preprocess_times);
        print_timing("TensorRT inference", inference_times);
        print_timing("Output copy", result_copy_times);
        std::cout << "Mean detections per frame: "
                  << static_cast<double>(detection_count) / measured_runs << '\n';
        std::cout << "Resolved output layout: classes=" << model.decoded_class_count()
                  << " objectness=" << (model.output_uses_objectness() ? "yes" : "no")
                  << " xyxy=" << (model.output_is_xyxy() ? "yes" : "no") << '\n';
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "Inference probe failed: " << error.what() << '\n';
        return 1;
    }
}
