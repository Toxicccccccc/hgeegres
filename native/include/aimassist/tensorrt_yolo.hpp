#pragma once

#include "aimassist/detection.hpp"

#include <NvInfer.h>
#include <cuda_runtime_api.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace aimassist
{
struct InferenceTimings
{
    double upload_preprocess_ms{};
    double predict_ms{};
    double result_copy_ms{};
};

struct InferenceResult
{
    std::vector<Detection> detections;
    InferenceTimings timings;
};

// Resolved interpretation of the model's output tensor, filled on each decode.
struct DecodedDetections
{
    int class_count{};
    bool uses_objectness{};
    bool xyxy_layout{};
};

class TensorRtYolo
{
public:
    // Accepts a TensorRT `.engine` plan, or an `.onnx` file which is parsed with
    // the ONNX parser and built into an engine (see ensure_engine_file).
    explicit TensorRtYolo(std::string const& engine_path, int device_index = 0);
    ~TensorRtYolo();

    TensorRtYolo(TensorRtYolo const&) = delete;
    TensorRtYolo& operator=(TensorRtYolo const&) = delete;

    InferenceResult infer(
        std::uint8_t const* bgra,
        int width,
        int height,
        float confidence_threshold,
        float nms_iou_threshold = 0.7F,
        int max_detections = 100
    );

    // Same inference, but the BGRA frame already lives in device memory (for
    // example straight from the DXGI capture's CUDA interop texture). This
    // skips the host upload entirely.
    InferenceResult infer_device(
        std::uint8_t const* device_bgra,
        int width,
        int height,
        float confidence_threshold,
        float nms_iou_threshold = 0.7F,
        int max_detections = 100
    );

    // A reusable device buffer for a BGRA frame of the given size. Capture code
    // can write into this and then call infer_device() on the returned pointer.
    std::uint8_t* device_frame_buffer(int width, int height);

    int input_width() const noexcept;
    int input_height() const noexcept;
    int class_count() const noexcept;
    // Layout resolved by the most recent decode (see DecodedDetections).
    int decoded_class_count() const noexcept;
    bool output_uses_objectness() const noexcept;
    bool output_is_xyxy() const noexcept;

private:
    class Logger;

    void ensure_device_frame_buffer(std::size_t required_bytes);
    void validate_inference_arguments(
        std::uint8_t const* bgra,
        int width,
        int height,
        float confidence_threshold,
        float nms_iou_threshold,
        int max_detections
    );
    InferenceResult run_device_pipeline(
        int width,
        int height,
        float confidence_threshold,
        float nms_iou_threshold,
        int max_detections,
        bool start_event_already_recorded
    );

    std::unique_ptr<Logger> logger_;
    std::unique_ptr<nvinfer1::IRuntime> runtime_;
    std::unique_ptr<nvinfer1::ICudaEngine> engine_;
    std::unique_ptr<nvinfer1::IExecutionContext> context_;
    cudaStream_t stream_{};
    cudaEvent_t event_start_{};
    cudaEvent_t event_preprocessed_{};
    cudaEvent_t event_inference_done_{};
    cudaEvent_t event_output_copied_{};
    void* device_bgra_{};
    float* device_input_{};
    float* device_output_{};
    int device_index_{};
    int input_width_{};
    int input_height_{};
    int class_count_{};
    int anchor_count_{};
    int output_rows_{};
    int output_columns_{};
    DecodedDetections decoded_layout_{};
    std::size_t capture_buffer_bytes_{};
    std::string input_name_;
    std::string output_name_;
    std::vector<float> host_output_;

public:
    // Build (or reuse a cached build of) an ONNX model into a TensorRT plan.
    // `source` may be an .onnx (parsed and built) or an .engine (returned as-is).
    // The plan is cached beside the source so the multi-minute build happens once
    // and every later start loads a compiled engine immediately.
    static std::string ensure_engine_file(std::string const& source);
};
} // namespace aimassist
