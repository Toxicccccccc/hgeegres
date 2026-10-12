#include "aimassist/tensorrt_yolo.hpp"

#include "aimassist/cuda_preprocess.hpp"

#include <NvInfer.h>
#include <cuda_runtime_api.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace
{
void check_cuda(cudaError_t status, char const* operation)
{
    if (status != cudaSuccess)
    {
        throw std::runtime_error(
            std::string(operation) + ": " + cudaGetErrorString(status)
        );
    }
}

std::vector<char> read_file(std::string const& path)
{
    std::ifstream file(path, std::ios::binary);
    if (!file)
    {
        throw std::runtime_error("Cannot open model file: " + path);
    }

    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

std::uint32_t read_u32_le(std::vector<char> const& data)
{
    if (data.size() < sizeof(std::uint32_t))
    {
        throw std::runtime_error("Model file is too short to contain its metadata header.");
    }

    auto const* bytes = reinterpret_cast<unsigned char const*>(data.data());
    return static_cast<std::uint32_t>(bytes[0])
        | (static_cast<std::uint32_t>(bytes[1]) << 8)
        | (static_cast<std::uint32_t>(bytes[2]) << 16)
        | (static_cast<std::uint32_t>(bytes[3]) << 24);
}

std::uint64_t read_u64_le(std::vector<char> const& data, std::size_t offset)
{
    std::uint64_t value = 0;
    for (int byte = 0; byte < 8; ++byte)
    {
        value |= static_cast<std::uint64_t>(
            static_cast<unsigned char>(data[offset + static_cast<std::size_t>(byte)])
        ) << (8 * byte);
    }
    return value;
}

// Returns the offset of the TensorRT plan inside the file and its byte length.
// Ultralytics exports prepend a JSON metadata header to the plan, while a raw
// TensorRT/trtexec plan starts immediately with the "ftrt" magic. Ultralytics
// also records the header length in a little-endian u64 trailer, so the file can
// be self-describing even when the leading u32 is not a valid header length.
std::pair<std::size_t, std::size_t> locate_plan(std::vector<char> const& data)
{
    if (data.size() < sizeof(std::uint32_t))
    {
        throw std::runtime_error("Model file is too short to be a TensorRT engine.");
    }

    auto const has_plan_magic = [](std::vector<char> const& buffer, std::size_t offset)
    {
        return offset + 4 <= buffer.size() && buffer[offset] == 'f' && buffer[offset + 1] == 't'
            && buffer[offset + 2] == 'r' && buffer[offset + 3] == 't';
    };

    // A raw plan already begins with the TensorRT magic, so use the whole file.
    if (has_plan_magic(data, 0))
    {
        return {0, data.size()};
    }

    // Ultralytics-wrapped plan: [u32 json length][json][plan][u64 json length].
    auto const metadata_size = static_cast<std::size_t>(read_u32_le(data));
    auto const plan_offset = sizeof(std::uint32_t) + metadata_size;
    if (metadata_size > 0 && plan_offset < data.size() && has_plan_magic(data, plan_offset))
    {
        return {plan_offset, data.size() - plan_offset};
    }

    // Fall back to the trailing u64 header length when the leading value is stale.
    if (data.size() >= sizeof(std::uint64_t))
    {
        auto const trailer_offset = data.size() - sizeof(std::uint64_t);
        auto const trailer_size = static_cast<std::size_t>(read_u64_le(data, trailer_offset));
        auto const trailer_plan_offset = trailer_offset - trailer_size;
        if (trailer_size > 0 && trailer_size <= trailer_offset
            && has_plan_magic(data, trailer_plan_offset))
        {
            return {trailer_plan_offset, trailer_offset - trailer_plan_offset};
        }
    }

    throw std::runtime_error(
        "Unrecognized TensorRT engine file: expected a raw plan or an Ultralytics-wrapped .engine."
    );
}

float intersection_over_union(
    aimassist::Detection const& left,
    aimassist::Detection const& right
)
{
    auto const width = std::max(0.0F, std::min(left.x2, right.x2) - std::max(left.x1, right.x1));
    auto const height = std::max(0.0F, std::min(left.y2, right.y2) - std::max(left.y1, right.y1));
    auto const intersection = width * height;
    auto const left_area = std::max(0.0F, left.x2 - left.x1)
        * std::max(0.0F, left.y2 - left.y1);
    auto const right_area = std::max(0.0F, right.x2 - right.x1)
        * std::max(0.0F, right.y2 - right.y1);
    auto const union_area = left_area + right_area - intersection;
    return union_area > 0.0F ? intersection / union_area : 0.0F;
}

// Cap the number of candidates carried into NMS. The reference applies the same
// idea: sorting/limiting before the O(n^2) suppression keeps a noisy frame from
// stalling the pipeline. Detection output is tiny next to the image, so this is
// about bounded worst-case cost rather than the average.
constexpr std::size_t max_pre_nms_candidates = 1000;

// Resolve how the output channels/rows map onto (4 or 5) box terms + classes.
// Ultralytics YOLOv8 exports as 4+classes with no objectness, while YOLOv5-style
// exports carry an extra objectness term; both appear in the wild.
bool resolve_class_layout(int extent, bool prefer_objectness, int* classes, bool* uses_objectness)
{
    if (extent <= 4)
    {
        return false;
    }
    // A single-class 5-wide row is ambiguous (1 class + objectness, or 5 = 4+1).
    // Default to the no-objectness reading, which matches Ultralytics exports.
    if (extent == 5)
    {
        *classes = 1;
        *uses_objectness = false;
        return true;
    }
    if (prefer_objectness)
    {
        *classes = extent - 5;
        *uses_objectness = true;
    }
    else
    {
        *classes = extent - 4;
        *uses_objectness = false;
    }
    return *classes > 0;
}

void add_cxcywh(
    std::vector<aimassist::Detection>& detections,
    float center_x,
    float center_y,
    float width,
    float height,
    float confidence,
    int class_id,
    float scale_x,
    float scale_y,
    float confidence_threshold
)
{
    if (!std::isfinite(confidence) || confidence < confidence_threshold
        || !std::isfinite(width) || !std::isfinite(height) || width <= 0.0F || height <= 0.0F)
    {
        return;
    }
    auto const half_width = width * 0.5F;
    auto const half_height = height * 0.5F;
    detections.push_back({
        (center_x - half_width) * scale_x,
        (center_y - half_height) * scale_y,
        (center_x + half_width) * scale_x,
        (center_y + half_height) * scale_y,
        confidence,
        class_id
    });
}

// Feature-major layout: each box term is one contiguous plane of `anchors`
// values, i.e. shape [1, 4+classes, anchors] (row count is the smaller extent).
void decode_feature_major(
    std::vector<float> const& output,
    int term_count,
    int anchor_count,
    int class_count,
    bool uses_objectness,
    float scale_x,
    float scale_y,
    float confidence_threshold,
    std::vector<aimassist::Detection>& detections,
    int max_candidates
)
{
    auto const plane = static_cast<std::size_t>(anchor_count);
    auto const class_base = static_cast<std::size_t>(uses_objectness ? 5 : 4);

    for (int anchor = 0; anchor < anchor_count; ++anchor)
    {
        auto const index = static_cast<std::size_t>(anchor);
        float best_confidence = 0.0F;
        int best_class = -1;
        for (int class_id = 0; class_id < class_count; ++class_id)
        {
            auto const confidence = output[(class_base + static_cast<std::size_t>(class_id)) * plane + index];
            if (confidence > best_confidence)
            {
                best_confidence = confidence;
                best_class = class_id;
            }
        }
        if (uses_objectness)
        {
            best_confidence *= output[4 * plane + index];
        }
        if (best_class < 0 || best_confidence < confidence_threshold)
        {
            continue;
        }
        add_cxcywh(
            detections,
            output[index],
            output[plane + index],
            output[2 * plane + index],
            output[3 * plane + index],
            best_confidence,
            best_class,
            scale_x,
            scale_y,
            confidence_threshold
        );
        if (static_cast<int>(detections.size()) >= max_candidates)
        {
            return;
        }
    }
    (void)term_count;
}

// Prediction-major layout: each detection is one contiguous row, i.e. shape
// [1, anchors, 4+classes]. For a single class, some exports emit [N, 6] as
// x1,y1,x2,y2,confidence,class_id.
void decode_prediction_major(
    std::vector<float> const& output,
    int row_count,
    int column_count,
    int class_count,
    bool uses_objectness,
    bool xyxy_layout,
    float scale_x,
    float scale_y,
    float confidence_threshold,
    std::vector<aimassist::Detection>& detections,
    int max_candidates
)
{
    auto const row_stride = static_cast<std::size_t>(column_count);
    auto const class_base = static_cast<std::size_t>(uses_objectness ? 5 : 4);

    for (int row = 0; row < row_count; ++row)
    {
        auto const base = static_cast<std::size_t>(row) * row_stride;

        if (xyxy_layout)
        {
            auto const confidence = output[base + 4];
            auto const class_id = static_cast<int>(std::lround(output[base + 5]));
            auto const x1 = output[base];
            auto const y1 = output[base + 1];
            auto const x2 = output[base + 2];
            auto const y2 = output[base + 3];
            if (std::isfinite(confidence) && confidence >= confidence_threshold
                && x2 > x1 && y2 > y1 && class_id >= 0)
            {
                detections.push_back({
                    x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y, confidence, class_id
                });
                if (static_cast<int>(detections.size()) >= max_candidates)
                {
                    return;
                }
            }
            continue;
        }

        float best_confidence = 0.0F;
        int best_class = -1;
        for (int class_id = 0; class_id < class_count; ++class_id)
        {
            auto const confidence = output[base + class_base + static_cast<std::size_t>(class_id)];
            if (confidence > best_confidence)
            {
                best_confidence = confidence;
                best_class = class_id;
            }
        }
        if (uses_objectness)
        {
            best_confidence *= output[base + 4];
        }
        if (best_class < 0 || best_confidence < confidence_threshold)
        {
            continue;
        }
        add_cxcywh(
            detections,
            output[base],
            output[base + 1],
            output[base + 2],
            output[base + 3],
            best_confidence,
            best_class,
            scale_x,
            scale_y,
            confidence_threshold
        );
        if (static_cast<int>(detections.size()) >= max_candidates)
        {
            return;
        }
    }
}

std::vector<aimassist::Detection> decode_yolov8(
    std::vector<float> const& output,
    int class_count_hint,
    int rows,
    int columns,
    int input_width,
    int input_height,
    int source_width,
    int source_height,
    float confidence_threshold,
    float nms_iou_threshold,
    int max_detections,
    aimassist::DecodedDetections* layout_out = nullptr
)
{
    auto const scale_x = static_cast<float>(source_width) / static_cast<float>(input_width);
    auto const scale_y = static_cast<float>(source_height) / static_cast<float>(input_height);
    std::vector<aimassist::Detection> candidates;
    // A pre-NMS cap of max(requested, requested*8) mirrors the reference: enough
    // headroom to keep the true boxes, bounded so suppression stays cheap.
    auto const requested = static_cast<std::size_t>(std::max(1, max_detections));
    auto const pre_nms_limit = std::min<long long>(
        static_cast<long long>(max_pre_nms_candidates),
        static_cast<long long>(requested) * 8
    );
    candidates.reserve(static_cast<std::size_t>(pre_nms_limit));

    int resolved_classes = std::max(1, class_count_hint);
    bool uses_objectness = false;
    bool xyxy_layout = false;

    if (columns == 6)
    {
        // Single-class xyxy row: [x1, y1, x2, y2, confidence, class_id].
        xyxy_layout = true;
        resolved_classes = 1;
        decode_prediction_major(
            output, rows, columns, resolved_classes, false, true,
            scale_x, scale_y, confidence_threshold, candidates,
            static_cast<int>(pre_nms_limit)
        );
    }
    else if (rows <= columns)
    {
        // Feature-major: row count is the smaller extent (4/5 + classes).
        if (!resolve_class_layout(rows, false, &resolved_classes, &uses_objectness))
        {
            return {};
        }
        decode_feature_major(
            output, rows, columns, resolved_classes, uses_objectness,
            scale_x, scale_y, confidence_threshold, candidates,
            static_cast<int>(pre_nms_limit)
        );
    }
    else
    {
        // Prediction-major: class terms live on the wider (column) axis.
        if (!resolve_class_layout(columns, true, &resolved_classes, &uses_objectness))
        {
            return {};
        }
        decode_prediction_major(
            output, rows, columns, resolved_classes, uses_objectness, false,
            scale_x, scale_y, confidence_threshold, candidates,
            static_cast<int>(pre_nms_limit)
        );
    }

    if (layout_out != nullptr)
    {
        layout_out->class_count = resolved_classes;
        layout_out->uses_objectness = uses_objectness;
        layout_out->xyxy_layout = xyxy_layout;
    }

    std::stable_sort(
        candidates.begin(),
        candidates.end(),
        [](aimassist::Detection const& left, aimassist::Detection const& right)
        {
            return left.confidence > right.confidence;
        }
    );

    std::vector<aimassist::Detection> selected;
    selected.reserve(static_cast<std::size_t>(std::max(0, max_detections)));
    for (auto const& candidate : candidates)
    {
        auto const overlaps_selected = std::any_of(
            selected.begin(),
            selected.end(),
            [&](aimassist::Detection const& kept)
            {
                return candidate.class_id == kept.class_id
                    && intersection_over_union(candidate, kept) > nms_iou_threshold;
            }
        );
        if (!overlaps_selected)
        {
            selected.push_back(candidate);
            if (static_cast<int>(selected.size()) >= max_detections)
            {
                break;
            }
        }
    }
    return selected;
}

std::string get_tensor_name(
    nvinfer1::ICudaEngine const& engine,
    nvinfer1::TensorIOMode mode
)
{
    for (int index = 0; index < engine.getNbIOTensors(); ++index)
    {
        auto const* name = engine.getIOTensorName(index);
        if (engine.getTensorIOMode(name) == mode)
        {
            return name;
        }
    }
    throw std::runtime_error(
        mode == nvinfer1::TensorIOMode::kINPUT
            ? "TensorRT engine has no input tensor."
            : "TensorRT engine has no output tensor."
    );
}

int checked_dimension(std::int64_t value)
{
    if (value <= 0 || value > std::numeric_limits<int>::max())
    {
        throw std::runtime_error("TensorRT engine has a dynamic or invalid tensor dimension.");
    }
    return static_cast<int>(value);
}

int checked_volume(nvinfer1::Dims const& dims)
{
    int volume = 1;
    for (int index = 0; index < dims.nbDims; ++index)
    {
        auto const dimension = checked_dimension(dims.d[index]);
        if (volume > std::numeric_limits<int>::max() / dimension)
        {
            throw std::runtime_error("TensorRT engine has a dynamic or invalid tensor shape.");
        }
        volume *= dimension;
    }
    return volume;
}
} // namespace

namespace aimassist
{
class TensorRtYolo::Logger final : public nvinfer1::ILogger
{
public:
    void log(Severity severity, char const* message) noexcept override
    {
        if (severity <= Severity::kWARNING)
        {
            std::cerr << "[TensorRT] " << message << '\n';
        }
    }
};

TensorRtYolo::TensorRtYolo(std::string const& engine_path, int device_index)
    : logger_(std::make_unique<Logger>()),
      device_index_(device_index)
{
    check_cuda(cudaSetDevice(device_index_), "Select CUDA device");

    auto const file_data = read_file(engine_path);
    auto const [plan_offset, plan_size] = locate_plan(file_data);

    runtime_.reset(nvinfer1::createInferRuntime(*logger_));
    if (!runtime_)
    {
        throw std::runtime_error("TensorRT could not create an inference runtime.");
    }

    engine_.reset(runtime_->deserializeCudaEngine(
        file_data.data() + plan_offset,
        plan_size
    ));
    if (!engine_)
    {
        throw std::runtime_error("TensorRT could not deserialize the engine payload.");
    }

    input_name_ = get_tensor_name(*engine_, nvinfer1::TensorIOMode::kINPUT);
    output_name_ = get_tensor_name(*engine_, nvinfer1::TensorIOMode::kOUTPUT);
    auto const input_shape = engine_->getTensorShape(input_name_.c_str());
    auto const output_shape = engine_->getTensorShape(output_name_.c_str());

    // Accept either YOLO output orientation: [1, 4+classes, anchors] (feature
    // major, Ultralytics YOLOv8/v11) or [1, anchors, 4+classes] (prediction
    // major). The decoder resolves which axis holds the class terms.
    if (input_shape.nbDims != 4 || input_shape.d[0] != 1 || input_shape.d[1] != 3
        || output_shape.nbDims != 3 || output_shape.d[0] != 1
        || output_shape.d[1] <= 0 || output_shape.d[2] <= 0
        || std::min(output_shape.d[1], output_shape.d[2]) <= 4)
    {
        throw std::runtime_error(
            "Expected a static batch-1 YOLO engine with NCHW input and a "
            "[1, 4+classes, anchors] or [1, anchors, 4+classes] output."
        );
    }
    if (engine_->getTensorDataType(input_name_.c_str()) != nvinfer1::DataType::kFLOAT
        || engine_->getTensorDataType(output_name_.c_str()) != nvinfer1::DataType::kFLOAT)
    {
        throw std::runtime_error("This engine currently requires FP32 input and output tensors.");
    }
    if (engine_->getTensorLocation(input_name_.c_str()) != nvinfer1::TensorLocation::kDEVICE
        || engine_->getTensorLocation(output_name_.c_str()) != nvinfer1::TensorLocation::kDEVICE)
    {
        throw std::runtime_error("This engine currently requires device-resident input and output tensors.");
    }

    input_height_ = checked_dimension(input_shape.d[2]);
    input_width_ = checked_dimension(input_shape.d[3]);
    output_rows_ = checked_dimension(output_shape.d[1]);
    output_columns_ = checked_dimension(output_shape.d[2]);
    // Provisional class count; the decoder resolves the exact layout per frame
    // (objectness vs. no objectness). Both primary layouts expose 4+classes on
    // one axis, so this is a correct read for the low-end estimate either way.
    class_count_ = std::min(output_rows_, output_columns_) - 4;
    anchor_count_ = std::max(output_rows_, output_columns_);
    host_output_.resize(static_cast<std::size_t>(checked_volume(output_shape)));

    context_.reset(engine_->createExecutionContext());
    if (!context_)
    {
        throw std::runtime_error("TensorRT could not create an execution context.");
    }
    check_cuda(cudaStreamCreateWithFlags(&stream_, cudaStreamNonBlocking), "Create CUDA stream");
    check_cuda(cudaEventCreate(&event_start_), "Create preprocessing timing event");
    check_cuda(cudaEventCreate(&event_preprocessed_), "Create inference timing event");
    check_cuda(cudaEventCreate(&event_inference_done_), "Create output timing event");
    check_cuda(cudaEventCreate(&event_output_copied_), "Create completion timing event");
    check_cuda(cudaMalloc(reinterpret_cast<void**>(&device_input_),
        static_cast<std::size_t>(checked_volume(input_shape)) * sizeof(float)),
        "Allocate TensorRT input");
    check_cuda(cudaMalloc(reinterpret_cast<void**>(&device_output_),
        host_output_.size() * sizeof(float)),
        "Allocate TensorRT output");

    if (!context_->setTensorAddress(input_name_.c_str(), device_input_)
        || !context_->setTensorAddress(output_name_.c_str(), device_output_))
    {
        throw std::runtime_error("TensorRT rejected an input or output device address.");
    }

    int device_count = 0;
    check_cuda(cudaGetDeviceCount(&device_count), "Query CUDA devices");
    if (device_index_ < 0 || device_index_ >= device_count)
    {
        throw std::runtime_error("Configured CUDA device index is out of range.");
    }
}

TensorRtYolo::~TensorRtYolo()
{
    if (device_bgra_ != nullptr)
    {
        cudaFree(device_bgra_);
    }
    if (device_input_ != nullptr)
    {
        cudaFree(device_input_);
    }
    if (device_output_ != nullptr)
    {
        cudaFree(device_output_);
    }
    if (event_start_ != nullptr)
    {
        cudaEventDestroy(event_start_);
    }
    if (event_preprocessed_ != nullptr)
    {
        cudaEventDestroy(event_preprocessed_);
    }
    if (event_inference_done_ != nullptr)
    {
        cudaEventDestroy(event_inference_done_);
    }
    if (event_output_copied_ != nullptr)
    {
        cudaEventDestroy(event_output_copied_);
    }
    if (stream_ != nullptr)
    {
        cudaStreamDestroy(stream_);
    }
}

void TensorRtYolo::ensure_device_frame_buffer(std::size_t required_bytes)
{
    if (device_bgra_ != nullptr && required_bytes == capture_buffer_bytes_)
    {
        return;
    }
    if (device_bgra_ != nullptr)
    {
        check_cuda(cudaFree(device_bgra_), "Release previous capture buffer");
        device_bgra_ = nullptr;
    }
    check_cuda(cudaMalloc(&device_bgra_, required_bytes), "Allocate capture buffer");
    capture_buffer_bytes_ = required_bytes;
}

std::uint8_t* TensorRtYolo::device_frame_buffer(int width, int height)
{
    check_cuda(cudaSetDevice(device_index_), "Select CUDA device");
    ensure_device_frame_buffer(
        static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4
    );
    return static_cast<std::uint8_t*>(device_bgra_);
}

void TensorRtYolo::validate_inference_arguments(
    std::uint8_t const* bgra,
    int width,
    int height,
    float confidence_threshold,
    float nms_iou_threshold,
    int max_detections
)
{
    if (bgra == nullptr || width <= 0 || height <= 0)
    {
        throw std::invalid_argument("Input frame must have valid BGRA pixels and dimensions.");
    }
    if (!std::isfinite(confidence_threshold) || confidence_threshold < 0.0F
        || confidence_threshold > 1.0F || !std::isfinite(nms_iou_threshold)
        || nms_iou_threshold < 0.0F || nms_iou_threshold > 1.0F || max_detections <= 0)
    {
        throw std::invalid_argument("Confidence, NMS threshold, and detection limit are invalid.");
    }
}

InferenceResult TensorRtYolo::infer(
    std::uint8_t const* bgra,
    int width,
    int height,
    float confidence_threshold,
    float nms_iou_threshold,
    int max_detections
)
{
    validate_inference_arguments(
        bgra, width, height, confidence_threshold, nms_iou_threshold, max_detections
    );

    check_cuda(cudaSetDevice(device_index_), "Select CUDA device");
    auto const stream = stream_;
    auto const required_capture_bytes = static_cast<std::size_t>(width)
        * static_cast<std::size_t>(height) * 4;
    ensure_device_frame_buffer(required_capture_bytes);

    // Host path: stage the CPU frame onto the device, then run the same device
    // pipeline. The upload shares the per-frame timing event so it stays visible
    // in telemetry.
    check_cuda(cudaEventRecord(event_start_, stream), "Record preprocessing start");
    check_cuda(cudaMemcpyAsync(
        device_bgra_,
        bgra,
        required_capture_bytes,
        cudaMemcpyHostToDevice,
        stream
    ), "Copy captured frame to CUDA device");
    return run_device_pipeline(
        width,
        height,
        confidence_threshold,
        nms_iou_threshold,
        max_detections,
        true
    );
}

InferenceResult TensorRtYolo::infer_device(
    std::uint8_t const* device_bgra,
    int width,
    int height,
    float confidence_threshold,
    float nms_iou_threshold,
    int max_detections
)
{
    validate_inference_arguments(
        device_bgra, width, height, confidence_threshold, nms_iou_threshold, max_detections
    );

    check_cuda(cudaSetDevice(device_index_), "Select CUDA device");
    ensure_device_frame_buffer(
        static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4
    );
    // The captured frame is already on the device; copy it into our buffer so
    // the caller's interop texture can be released independently of inference.
    check_cuda(cudaEventRecord(event_start_, stream_), "Record preprocessing start");
    check_cuda(cudaMemcpyAsync(
        device_bgra_,
        device_bgra,
        static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4,
        cudaMemcpyDeviceToDevice,
        stream_
    ), "Copy captured device frame into the inference buffer");
    return run_device_pipeline(
        width,
        height,
        confidence_threshold,
        nms_iou_threshold,
        max_detections,
        true
    );
}

InferenceResult TensorRtYolo::run_device_pipeline(
    int width,
    int height,
    float confidence_threshold,
    float nms_iou_threshold,
    int max_detections,
    bool start_event_already_recorded
)
{
    auto const stream = stream_;
    if (!start_event_already_recorded)
    {
        check_cuda(cudaEventRecord(event_start_, stream), "Record preprocessing start");
    }
    launch_bgra_to_rgb_nchw(
        static_cast<std::uint8_t const*>(device_bgra_),
        width,
        height,
        device_input_,
        input_width_,
        input_height_,
        stream
    );

    InferenceResult result;
    check_cuda(cudaEventRecord(event_preprocessed_, stream), "Record preprocessing completion");

    if (!context_->enqueueV3(stream))
    {
        throw std::runtime_error("TensorRT enqueueV3 failed.");
    }
    check_cuda(cudaEventRecord(event_inference_done_, stream), "Record inference completion");

    check_cuda(cudaMemcpyAsync(
        host_output_.data(),
        device_output_,
        host_output_.size() * sizeof(float),
        cudaMemcpyDeviceToHost,
        stream
    ), "Copy TensorRT output to host");
    check_cuda(cudaEventRecord(event_output_copied_, stream), "Record output copy completion");
    check_cuda(cudaStreamSynchronize(stream), "Wait for TensorRT inference");
    float upload_preprocess_ms = 0.0F;
    float predict_ms = 0.0F;
    float result_copy_ms = 0.0F;
    check_cuda(cudaEventElapsedTime(
        &upload_preprocess_ms,
        event_start_,
        event_preprocessed_
    ), "Measure CUDA preprocessing time");
    check_cuda(cudaEventElapsedTime(
        &predict_ms,
        event_preprocessed_,
        event_inference_done_
    ), "Measure TensorRT inference time");
    check_cuda(cudaEventElapsedTime(
        &result_copy_ms,
        event_inference_done_,
        event_output_copied_
    ), "Measure result transfer time");
    result.timings.upload_preprocess_ms = upload_preprocess_ms;
    result.timings.predict_ms = predict_ms;
    result.timings.result_copy_ms = result_copy_ms;
    result.detections = decode_yolov8(
        host_output_,
        class_count_,
        output_rows_,
        output_columns_,
        input_width_,
        input_height_,
        width,
        height,
        confidence_threshold,
        nms_iou_threshold,
        max_detections,
        &decoded_layout_
    );
    return result;
}

int TensorRtYolo::input_width() const noexcept
{
    return input_width_;
}

int TensorRtYolo::input_height() const noexcept
{
    return input_height_;
}

int TensorRtYolo::class_count() const noexcept
{
    return class_count_;
}

int TensorRtYolo::decoded_class_count() const noexcept
{
    return decoded_layout_.class_count;
}

bool TensorRtYolo::output_uses_objectness() const noexcept
{
    return decoded_layout_.uses_objectness;
}

bool TensorRtYolo::output_is_xyxy() const noexcept
{
    return decoded_layout_.xyxy_layout;
}
} // namespace aimassist
