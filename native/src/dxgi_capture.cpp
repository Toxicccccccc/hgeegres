#include "aimassist/dxgi_capture.hpp"

#include <Windows.h>
#include <cstdio>
#include <d3d11.h>
#include <dxgi1_2.h>

#include <cuda_d3d11_interop.h>
#include <cuda_runtime_api.h>

#include <cstring>
#include <string>

namespace
{
template <typename T>
void safe_release(T*& pointer)
{
    if (pointer != nullptr)
    {
        pointer->Release();
        pointer = nullptr;
    }
}

std::string hresult_text(char const* operation, HRESULT result)
{
    char buffer[16]{};
    std::snprintf(buffer, sizeof(buffer), "%08lX", static_cast<unsigned long>(result));
    return std::string(operation) + " failed with HRESULT 0x" + buffer;
}
} // namespace

namespace aimassist
{
DxgiDesktopCapture::~DxgiDesktopCapture()
{
    release();
}

bool DxgiDesktopCapture::initialize(int monitor_index, std::string& status)
{
    release();
    monitor_index_ = monitor_index;

    IDXGIFactory1* factory = nullptr;
    auto result = CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&factory));
    if (FAILED(result))
    {
        status = hresult_text("CreateDXGIFactory1", result);
        return false;
    }

    IDXGIAdapter1* adapter = nullptr;
    IDXGIOutput* output = nullptr;
    auto const target = monitor_index < 0 ? 0 : monitor_index;
    int current = 0;
    bool found = false;

    for (UINT adapter_index = 0; !found; ++adapter_index)
    {
        IDXGIAdapter1* candidate_adapter = nullptr;
        result = factory->EnumAdapters1(adapter_index, &candidate_adapter);
        if (result == DXGI_ERROR_NOT_FOUND)
        {
            break;
        }
        if (FAILED(result))
        {
            status = hresult_text("EnumAdapters1", result);
            safe_release(factory);
            return false;
        }

        for (UINT output_index = 0;; ++output_index)
        {
            IDXGIOutput* candidate_output = nullptr;
            result = candidate_adapter->EnumOutputs(output_index, &candidate_output);
            if (result == DXGI_ERROR_NOT_FOUND)
            {
                break;
            }
            if (FAILED(result))
            {
                status = hresult_text("EnumOutputs", result);
                safe_release(candidate_adapter);
                safe_release(factory);
                return false;
            }
            if (current == target)
            {
                adapter = candidate_adapter;
                output = candidate_output;
                found = true;
                break;
            }
            ++current;
            safe_release(candidate_output);
        }

        if (!found)
        {
            safe_release(candidate_adapter);
        }
    }

    if (!found || adapter == nullptr || output == nullptr)
    {
        status = "No monitor available at index " + std::to_string(target);
        safe_release(adapter);
        safe_release(output);
        safe_release(factory);
        return false;
    }

    D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_0};
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    result = D3D11CreateDevice(
        adapter,
        D3D_DRIVER_TYPE_UNKNOWN,
        nullptr,
        0,
        levels,
        1,
        D3D11_SDK_VERSION,
        &device,
        nullptr,
        &context
    );
    if (FAILED(result))
    {
        status = hresult_text("D3D11CreateDevice", result);
        safe_release(output);
        safe_release(adapter);
        safe_release(factory);
        return false;
    }

    // Keep at most one queued frame so the duplication never lags the desktop.
    IDXGIDevice1* dxgi_device = nullptr;
    if (SUCCEEDED(device->QueryInterface(__uuidof(IDXGIDevice1), reinterpret_cast<void**>(&dxgi_device))))
    {
        dxgi_device->SetMaximumFrameLatency(1);
        safe_release(dxgi_device);
    }

    IDXGIOutput1* output1 = nullptr;
    result = output->QueryInterface(__uuidof(IDXGIOutput1), reinterpret_cast<void**>(&output1));
    if (FAILED(result))
    {
        status = hresult_text("QueryInterface(IDXGIOutput1)", result);
        safe_release(context);
        safe_release(device);
        safe_release(output);
        safe_release(adapter);
        safe_release(factory);
        return false;
    }

    IDXGIOutputDuplication* duplication = nullptr;
    result = output1->DuplicateOutput(device, &duplication);
    if (FAILED(result))
    {
        status = hresult_text("DuplicateOutput", result);
        safe_release(output1);
        safe_release(context);
        safe_release(device);
        safe_release(output);
        safe_release(adapter);
        safe_release(factory);
        return false;
    }

    DXGI_OUTPUT_DESC output_description{};
    output->GetDesc(&output_description);
    screen_width_ = output_description.DesktopCoordinates.right - output_description.DesktopCoordinates.left;
    screen_height_ = output_description.DesktopCoordinates.bottom - output_description.DesktopCoordinates.top;

    device_ = device;
    context_ = context;
    duplication_ = duplication;
    output1_ = output1;

    safe_release(output);
    safe_release(adapter);
    safe_release(factory);

    status = "Desktop Duplication initialized on monitor " + std::to_string(target)
        + " (" + std::to_string(screen_width_) + "x" + std::to_string(screen_height_) + ")";
    return true;
}

bool DxgiDesktopCapture::create_staging_texture(int fov)
{
    auto* device = static_cast<ID3D11Device*>(device_);
    if (device == nullptr)
    {
        return false;
    }
    safe_release(reinterpret_cast<ID3D11Texture2D*&>(staging_texture_));

    D3D11_TEXTURE2D_DESC description{};
    description.Width = static_cast<UINT>(fov);
    description.Height = static_cast<UINT>(fov);
    description.MipLevels = 1;
    description.ArraySize = 1;
    description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    description.SampleDesc.Count = 1;
    description.Usage = D3D11_USAGE_STAGING;
    description.BindFlags = 0;
    description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;

    ID3D11Texture2D* texture = nullptr;
    if (FAILED(device->CreateTexture2D(&description, nullptr, &texture)))
    {
        return false;
    }
    staging_texture_ = texture;
    return true;
}

bool DxgiDesktopCapture::create_interop_texture(int fov)
{
    auto* device = static_cast<ID3D11Device*>(device_);
    if (device == nullptr)
    {
        return false;
    }

    // Release only the previous interop pair, not the staging texture.
    if (cuda_interop_ != nullptr)
    {
        cudaGraphicsUnregisterResource(static_cast<cudaGraphicsResource*>(cuda_interop_));
        cuda_interop_ = nullptr;
    }
    safe_release(reinterpret_cast<ID3D11Texture2D*&>(interop_texture_));

    D3D11_TEXTURE2D_DESC description{};
    description.Width = static_cast<UINT>(fov);
    description.Height = static_cast<UINT>(fov);
    description.MipLevels = 1;
    description.ArraySize = 1;
    description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    description.SampleDesc.Count = 1;
    description.Usage = D3D11_USAGE_DEFAULT;
    description.BindFlags = D3D11_BIND_SHADER_RESOURCE;

    ID3D11Texture2D* texture = nullptr;
    if (FAILED(device->CreateTexture2D(&description, nullptr, &texture)))
    {
        return false;
    }

    cudaGraphicsResource* resource = nullptr;
    if (cudaGraphicsD3D11RegisterResource(&resource, texture, cudaGraphicsRegisterFlagsNone)
        != cudaSuccess)
    {
        safe_release(texture);
        return false;
    }

    interop_texture_ = texture;
    cuda_interop_ = resource;
    return true;
}

bool DxgiDesktopCapture::enable_cuda_interop(std::string& status)
{
    if (cuda_interop_ != nullptr)
    {
        status = "CUDA/D3D11 interop already enabled";
        return true;
    }
    if (interop_texture_ == nullptr)
    {
        // The interop texture is created lazily with the first capture, because
        // it must match the FOV size.
        status = "CUDA/D3D11 interop will be enabled on the first capture";
        return true;
    }

    cudaGraphicsResource* resource = nullptr;
    auto const result = cudaGraphicsD3D11RegisterResource(
        &resource,
        static_cast<ID3D11Texture2D*>(interop_texture_),
        cudaGraphicsRegisterFlagsNone
    );
    if (result != cudaSuccess)
    {
        status = std::string("cudaGraphicsD3D11RegisterResource failed: ") + cudaGetErrorString(result);
        return false;
    }
    cuda_interop_ = resource;
    status = "CUDA/D3D11 interop enabled";
    return true;
}

bool DxgiDesktopCapture::cuda_interop_ready() const noexcept
{
    return cuda_interop_ != nullptr;
}

bool DxgiDesktopCapture::acquire_frame(bool& had_new_frame, std::string& status)
{
    auto* duplication = static_cast<IDXGIOutputDuplication*>(duplication_);
    if (duplication == nullptr)
    {
        status = "Duplication interface is not initialized";
        return false;
    }

    DXGI_OUTDUPL_FRAME_INFO frame_info{};
    IDXGIResource* resource = nullptr;
    auto const result = duplication->AcquireNextFrame(0, &frame_info, &resource);

    if (result == DXGI_ERROR_WAIT_TIMEOUT)
    {
        // No desktop change since the last frame: re-use the previous one.
        had_new_frame = false;
        return true;
    }
    if (result == DXGI_ERROR_ACCESS_LOST || result == DXGI_ERROR_DEVICE_RESET
        || result == DXGI_ERROR_DEVICE_REMOVED || result == DXGI_ERROR_INVALID_CALL)
    {
        status = "Desktop Duplication access lost; reinitialize required";
        return false;
    }
    if (FAILED(result))
    {
        status = hresult_text("AcquireNextFrame", result);
        return false;
    }

    frame_acquired_ = true;
    ID3D11Texture2D* desktop_texture = nullptr;
    if (resource != nullptr)
    {
        resource->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&desktop_texture));
        safe_release(resource);
    }
    if (desktop_texture == nullptr)
    {
        had_new_frame = false;
        return true;
    }

    // Copy only the FOV rectangle out of the desktop texture. This is a GPU-side
    // region copy, which is why a whole-frame CPU readback is unnecessary.
    D3D11_BOX region{};
    region.left = static_cast<UINT>(region_left_ < 0 ? 0 : region_left_);
    region.top = static_cast<UINT>(region_top_ < 0 ? 0 : region_top_);
    region.front = 0;
    region.right = region.left + static_cast<UINT>(region_size_);
    region.bottom = region.top + static_cast<UINT>(region_size_);
    region.back = 1;

    auto* context = static_cast<ID3D11DeviceContext*>(context_);
    auto* target_texture = static_cast<ID3D11Texture2D*>(
        cuda_interop_ != nullptr ? interop_texture_ : staging_texture_
    );
    context->CopySubresourceRegion(target_texture, 0, 0, 0, 0, desktop_texture, 0, &region);
    safe_release(desktop_texture);
    had_new_frame = true;
    return true;
}

bool DxgiDesktopCapture::capture(
    int fov,
    int left,
    int top,
    int timeout_ms,
    bool& had_new_frame,
    std::string& status
)
{
    (void)timeout_ms;
    if (fov <= 0)
    {
        status = "FOV must be positive";
        return false;
    }
    if (duplication_ == nullptr || device_ == nullptr || context_ == nullptr)
    {
        status = "Desktop Duplication is not initialized";
        return false;
    }

    if (region_size_ != fov)
    {
        if (!create_staging_texture(fov))
        {
            status = "Could not create the FOV staging texture";
            return false;
        }
        if (!create_interop_texture(fov))
        {
            status = "Could not create the FOV interop texture";
            return false;
        }
        region_size_ = fov;
    }
    region_left_ = left;
    region_top_ = top;

    frame_acquired_ = false;
    if (!acquire_frame(had_new_frame, status))
    {
        return false;
    }
    if (!had_new_frame)
    {
        return true;
    }

    auto* context = static_cast<ID3D11DeviceContext*>(context_);

    if (cuda_interop_ != nullptr)
    {
        // Fast path: the frame already sits in the CUDA-registered texture.
        has_cpu_frame_ = false;
    }
    else
    {
        // Fallback: map the staging texture and copy the crop to system memory.
        D3D11_MAPPED_SUBRESOURCE mapped{};
        if (FAILED(context->Map(
                static_cast<ID3D11Texture2D*>(staging_texture_),
                0,
                D3D11_MAP_READ,
                0,
                &mapped)))
        {
            status = "Mapping the staging texture failed";
            return false;
        }
        auto const row_bytes = static_cast<std::size_t>(fov) * 4;
        cpu_frame_.resize(row_bytes * static_cast<std::size_t>(fov));
        for (int row = 0; row < fov; ++row)
        {
            std::memcpy(
                cpu_frame_.data() + static_cast<std::size_t>(row) * row_bytes,
                static_cast<std::uint8_t const*>(mapped.pData) + static_cast<std::size_t>(row) * mapped.RowPitch,
                row_bytes
            );
        }
        context->Unmap(static_cast<ID3D11Texture2D*>(staging_texture_), 0);
        has_cpu_frame_ = true;
    }

    if (frame_acquired_)
    {
        static_cast<IDXGIOutputDuplication*>(duplication_)->ReleaseFrame();
        frame_acquired_ = false;
    }
    return true;
}

bool DxgiDesktopCapture::copy_to_device(std::uint8_t* device_destination, int fov)
{
    if (cuda_interop_ == nullptr || device_destination == nullptr || fov <= 0)
    {
        return false;
    }

    auto* resource = static_cast<cudaGraphicsResource*>(cuda_interop_);
    if (cudaGraphicsMapResources(1, &resource, nullptr) != cudaSuccess)
    {
        return false;
    }

    cudaArray_t array = nullptr;
    auto const mapped = cudaGraphicsSubResourceGetMappedArray(&array, resource, 0, 0);
    if (mapped != cudaSuccess)
    {
        cudaGraphicsUnmapResources(1, &resource, nullptr);
        return false;
    }

    // Copy the CUDA array into the caller's linear device buffer.
    auto const result = cudaMemcpy2DFromArray(
        device_destination,
        static_cast<std::size_t>(fov) * 4,
        array,
        0,
        0,
        static_cast<std::size_t>(fov) * 4,
        static_cast<std::size_t>(fov),
        cudaMemcpyDeviceToDevice
    );

    auto const unmap = cudaGraphicsUnmapResources(1, &resource, nullptr);
    return result == cudaSuccess && unmap == cudaSuccess;
}

std::vector<std::uint8_t> const& DxgiDesktopCapture::cpu_frame() const noexcept
{
    return cpu_frame_;
}

bool DxgiDesktopCapture::has_cpu_frame() const noexcept
{
    return has_cpu_frame_;
}

bool DxgiDesktopCapture::initialized() const noexcept
{
    return duplication_ != nullptr;
}

int DxgiDesktopCapture::screen_width() const noexcept
{
    return screen_width_;
}

int DxgiDesktopCapture::screen_height() const noexcept
{
    return screen_height_;
}

void DxgiDesktopCapture::release()
{
    if (duplication_ != nullptr && frame_acquired_)
    {
        static_cast<IDXGIOutputDuplication*>(duplication_)->ReleaseFrame();
        frame_acquired_ = false;
    }
    if (cuda_interop_ != nullptr)
    {
        cudaGraphicsUnregisterResource(static_cast<cudaGraphicsResource*>(cuda_interop_));
        cuda_interop_ = nullptr;
    }
    safe_release(reinterpret_cast<ID3D11Texture2D*&>(interop_texture_));
    safe_release(reinterpret_cast<ID3D11Texture2D*&>(staging_texture_));
    safe_release(reinterpret_cast<IDXGIOutputDuplication*&>(duplication_));
    safe_release(reinterpret_cast<IDXGIOutput1*&>(output1_));
    safe_release(reinterpret_cast<ID3D11DeviceContext*&>(context_));
    safe_release(reinterpret_cast<ID3D11Device*&>(device_));

    region_size_ = 0;
    has_cpu_frame_ = false;
    cpu_frame_.clear();
}
} // namespace aimassist
