#include <NvInfer.h>
#include <cuda_runtime_api.h>

#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
class TensorRtLogger final : public nvinfer1::ILogger
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

template <typename T>
using TensorRtPtr = std::unique_ptr<T>;

std::vector<char> read_file(std::string const& path)
{
    std::ifstream file(path, std::ios::binary);
    if (!file)
    {
        throw std::runtime_error("Cannot open model file: " + path);
    }

    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

std::uint32_t read_u32_le(std::vector<char> const& data, std::size_t offset)
{
    auto const* bytes = reinterpret_cast<unsigned char const*>(data.data()) + offset;
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

struct PlanLocation
{
    std::size_t plan_offset{};
    std::size_t plan_size{};
    std::size_t metadata_offset{};
    std::size_t metadata_size{};
};

// Accepts a raw TensorRT plan (leading "ftrt" magic) or an Ultralytics-wrapped
// plan ([u32 json length][json][plan][u64 json length]).
PlanLocation locate_plan(std::vector<char> const& data)
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

    if (has_plan_magic(data, 0))
    {
        return {0, data.size(), 0, 0};
    }

    auto const metadata_size = static_cast<std::size_t>(read_u32_le(data, 0));
    auto const plan_offset = sizeof(std::uint32_t) + metadata_size;
    if (metadata_size > 0 && plan_offset < data.size() && has_plan_magic(data, plan_offset))
    {
        return {plan_offset, data.size() - plan_offset, sizeof(std::uint32_t), metadata_size};
    }

    if (data.size() >= sizeof(std::uint64_t))
    {
        auto const trailer_offset = data.size() - sizeof(std::uint64_t);
        auto const trailer_size = static_cast<std::size_t>(read_u64_le(data, trailer_offset));
        auto const trailer_plan_offset = trailer_offset - trailer_size;
        if (trailer_size > 0 && trailer_size <= trailer_offset
            && has_plan_magic(data, trailer_plan_offset))
        {
            return {
                trailer_plan_offset,
                trailer_offset - trailer_plan_offset,
                sizeof(std::uint32_t),
                trailer_plan_offset - sizeof(std::uint32_t)
            };
        }
    }

    throw std::runtime_error(
        "Unrecognized TensorRT engine file: expected a raw plan or an Ultralytics-wrapped .engine."
    );
}

std::string dims_to_string(nvinfer1::Dims const& dims)
{
    std::string result = "[";
    for (int index = 0; index < dims.nbDims; ++index)
    {
        if (index != 0)
        {
            result += ", ";
        }
        result += std::to_string(dims.d[index]);
    }
    result += "]";
    return result;
}

char const* data_type_name(nvinfer1::DataType type)
{
    switch (type)
    {
    case nvinfer1::DataType::kFLOAT:
        return "float32";
    case nvinfer1::DataType::kHALF:
        return "float16";
    case nvinfer1::DataType::kINT8:
        return "int8";
    case nvinfer1::DataType::kINT32:
        return "int32";
    case nvinfer1::DataType::kBOOL:
        return "bool";
    case nvinfer1::DataType::kUINT8:
        return "uint8";
    default:
        return "other";
    }
}

void run_probe(std::string const& path)
{
    int device_count = 0;
    auto const cuda_status = cudaGetDeviceCount(&device_count);
    if (cuda_status != cudaSuccess || device_count == 0)
    {
        throw std::runtime_error(
            std::string("No CUDA device is available: ")
            + cudaGetErrorString(cuda_status)
        );
    }

    cudaDeviceProp device{};
    if (cudaGetDeviceProperties(&device, 0) != cudaSuccess)
    {
        throw std::runtime_error("Could not query CUDA device 0.");
    }

    auto const file_data = read_file(path);
    auto const location = locate_plan(file_data);
    if (location.plan_offset + location.plan_size > file_data.size())
    {
        throw std::runtime_error("Located TensorRT plan lies outside the model file.");
    }

    std::string const metadata = location.metadata_size > 0
        ? std::string(file_data.data() + location.metadata_offset, location.metadata_size)
        : std::string{};
    auto const* plan = file_data.data() + location.plan_offset;
    auto const plan_size = location.plan_size;

    TensorRtLogger logger;
    TensorRtPtr<nvinfer1::IRuntime> runtime{nvinfer1::createInferRuntime(logger)};
    if (!runtime)
    {
        throw std::runtime_error("TensorRT could not create an inference runtime.");
    }

    TensorRtPtr<nvinfer1::ICudaEngine> engine{
        runtime->deserializeCudaEngine(plan, plan_size)
    };
    if (!engine)
    {
        throw std::runtime_error("TensorRT could not deserialize the engine payload.");
    }

    std::cout << "GPU: " << device.name << " (sm_" << device.major << device.minor << ")\n";
    std::cout << "TensorRT: " << NV_TENSORRT_MAJOR << '.' << NV_TENSORRT_MINOR
              << '.' << NV_TENSORRT_PATCH << '\n';
    std::cout << "Plan layout: "
              << (location.metadata_size > 0 ? "Ultralytics-wrapped" : "raw TensorRT plan")
              << " (plan offset " << location.plan_offset << ", " << location.plan_size << " bytes)\n";
    std::cout << "Model metadata bytes: " << location.metadata_size << '\n';
    if (!metadata.empty())
    {
        std::cout << "Model metadata: " << metadata << '\n';
    }
    std::cout << "Tensor count: " << engine->getNbIOTensors() << '\n';

    for (int index = 0; index < engine->getNbIOTensors(); ++index)
    {
        auto const* name = engine->getIOTensorName(index);
        auto const mode = engine->getTensorIOMode(name);
        auto const tensor_location = engine->getTensorLocation(name);
        std::cout << name
                  << " mode=" << (mode == nvinfer1::TensorIOMode::kINPUT ? "input" : "output")
                  << " shape=" << dims_to_string(engine->getTensorShape(name))
                  << " type=" << data_type_name(engine->getTensorDataType(name))
                  << " location="
                  << (tensor_location == nvinfer1::TensorLocation::kDEVICE ? "device" : "host")
                  << '\n';
    }
}
} // namespace

int main(int argc, char** argv)
{
    if (argc != 2)
    {
        std::cerr << "Usage: native_engine_probe <.engine path>\n";
        return 2;
    }

    try
    {
        run_probe(argv[1]);
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "Native TensorRT probe failed: " << error.what() << '\n';
        return 1;
    }
}
