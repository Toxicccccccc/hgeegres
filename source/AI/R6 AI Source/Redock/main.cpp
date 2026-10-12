#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <thread>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <cstring>
#include <random>
#include <algorithm>
#include <cmath>
#include <Windows.h>
#include <conio.h>
#include <ShellScalingAPI.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <timeapi.h>

#include "vhid_interface.h"

#include <opencv2/opencv.hpp>
#include <onnxruntime_cxx_api.h>
#include <dml_provider_factory.h>

#pragma comment(lib, "User32.lib")
#pragma comment(lib, "Gdi32.lib")
#pragma comment(lib, "Shcore.lib")
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "winmm.lib")

namespace fs = std::filesystem;

// --- UTILITIES ---
std::string GenerateRandomString(int len) {
    static const char charset[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    std::string s;
    s.reserve(len);
    for (int i = 0; i < len; ++i) {
        s += charset[rand() % (sizeof(charset) - 1)];
    }
    return s;
}

// --- XOR OBFUSCATION TOOL ---
template <unsigned int N>
struct XorStr {
    char data[N];
    constexpr XorStr(const char* str) : data{} {
        for (unsigned int i = 0; i < N; i++) data[i] = str[i] ^ 0x5A;
    }
};

#define X(str) []{ \
    constexpr auto x = XorStr<sizeof(str)>(str); \
    std::string out; \
    for(int i=0; i<sizeof(str); i++) out += (char)(x.data[i] ^ 0x5A); \
    return out; \
}().c_str()

// --- CONFIGURATION ---
const std::wstring MODEL_PATH = L"best_fp16.onnx";
const int MODEL_SIZE = 320;
const std::string CONFIG_FILE = "settings.cfg";

// Adjustable Settings
int fov_radius = 150;
int frame_limit = 144;
float conf_threshold = 0.65f;
float aim_sens = 0.30f;        // Base sensitivity
float smoothing_val = 0.55f;   // Base smoothing
float recoil_strength = 1.0f;

bool recoil_enabled = true;
bool triggerbot_enabled = false;
bool trigger_auto_mode = false;
bool screenshots_enabled = true;
bool show_confidence = true;
bool show_distance = true;
bool overlay_enabled = true;

const float PREDICTION_MULT = 0.45f; // Increased for better leading
const float MAX_MOVE_SPEED = 45.0f;
const float MIN_DIST_THRESHOLD = 0.50f;
const float STICKY_DISTANCE = 45.0f;
const float TARGET_LOCK_BONUS = 60.0f;
const int MAX_LOST_FRAMES = 5;
const float PYTHON_AIM_HEIGHT = 0.06f; // Lifted from 0.15 to avoid shoulder-aiming
const std::string SCREENSHOT_DIR = "screenshots";

// --- GLOBALS ---
bool is_auto_firing = false;
bool running = true;
bool g_restart_requested = false;
std::atomic<bool> g_ai_active{ true };

constexpr float kInv255 = 1.0f / 255.0f;

struct TargetCandidate {
    int x, y, h, w;
    float conf;
};

struct DetectionResult {
    std::vector<TargetCandidate> candidates;
    std::vector<int> overlay_data;
};

std::mutex frame_mtx;
std::condition_variable frame_cv;
cv::Mat bufferA, bufferB;
cv::Mat* write_buf = &bufferA;
cv::Mat* read_buf = &bufferB;
bool frame_ready = false;

std::mutex result_mtx;
DetectionResult shared_result;

typedef void (*InitOverlayFunc)(int, int, int);
typedef void (*UpdateOverlayFunc)(int*, int, float);
typedef void (*CleanupFunc)();

InitOverlayFunc init_overlay = nullptr;
UpdateOverlayFunc update_overlay = nullptr;
CleanupFunc overlay_cleanup = nullptr;

class VhidMouse {
    HANDLE device = INVALID_HANDLE_VALUE;
    unsigned char button_state = 0;
    DWORD last_open_error = 0;
    DWORD last_ioctl_error = 0;
    bool injection_ready = false;

    bool SendRequest(long dx, long dy, unsigned char buttons, unsigned char wheel = 0) {
        if (device == INVALID_HANDLE_VALUE) return false;

        MOUSE_MOVE_REQUEST move = { dx, dy, buttons, wheel };

        VHID_SECURE_PACKET packet = {};
        packet.Type = PacketType_Mouse;
        packet.Size = (unsigned char)sizeof(MOUSE_MOVE_REQUEST);
        memcpy(packet.Payload, &move, sizeof(move));

        unsigned char* raw = reinterpret_cast<unsigned char*>(&packet);
        for (size_t i = 0; i < sizeof(packet); ++i) {
            raw[i] ^= VHID_ENCRYPTION_KEY;
        }

        DWORD bytes_returned = 0;
        SetLastError(0);
        BOOL ok = DeviceIoControl(
            device,
            IOCTL_VHID_SECURE_INPUT,
            &packet,
            sizeof(packet),
            nullptr,
            0,
            &bytes_returned,
            nullptr);
        if (!ok) {
            last_ioctl_error = GetLastError();
            injection_ready = false;
            return false;
        }
        injection_ready = true;
        return true;
    }

public:
    bool Open() {
        last_open_error = 0;
        injection_ready = false;
        device = CreateFileW(
            L"\\\\.\\VHIDMouse",
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            nullptr,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            nullptr);
        if (device == INVALID_HANDLE_VALUE) {
            last_open_error = GetLastError();
            return false;
        }
        return true;
    }

    // Device handle is open; IOCTL proves mouclass callback was found (WDM driver).
    bool ProbeInjection() {
        return SendRequest(0, 0, 0);
    }

    bool IsInjectionReady() const { return injection_ready; }
    DWORD LastOpenError() const { return last_open_error; }
    DWORD LastIoctlError() const { return last_ioctl_error; }

    void Close() {
        if (device != INVALID_HANDLE_VALUE) {
            CloseHandle(device);
            device = INVALID_HANDLE_VALUE;
        }
        injection_ready = false;
    }

    bool IsOpen() const { return device != INVALID_HANDLE_VALUE; }

    bool Move(int dx, int dy) {
        return SendRequest(dx, dy, button_state);
    }

    bool Click(int action) {
        if (action == 1) {
            button_state = 1;
            return SendRequest(0, 0, button_state);
        }
        if (action == 2) {
            button_state = 0;
            return SendRequest(0, 0, button_state);
        }
        return false;
    }
};

VhidMouse vhid_mouse;

std::string g_driver_status;

void WaitForContinue(const char* prompt) {
    std::cout << prompt << std::endl;
    std::cout.flush();
    (void)_getch();
}

enum class DriverConnectResult {
    Ok,
    DeviceNotFound,
    InjectionFailed
};

// --- FILE SYSTEM ---
void SaveConfig() {
    std::ofstream f(CONFIG_FILE);
    if (f.is_open()) {
        f << fov_radius << "\n" << conf_threshold << "\n" << aim_sens << "\n"
            << smoothing_val << "\n" << recoil_strength << "\n" << (int)recoil_enabled << "\n"
            << (int)triggerbot_enabled << "\n" << (int)trigger_auto_mode << "\n"
            << (int)overlay_enabled << "\n" << (int)screenshots_enabled << "\n" << frame_limit;
        f.close();
    }
}

void LoadConfig() {
    std::ifstream f(CONFIG_FILE);
    if (f.is_open()) {
        f >> fov_radius >> conf_threshold >> aim_sens >> smoothing_val >> recoil_strength
            >> recoil_enabled >> triggerbot_enabled >> trigger_auto_mode >> overlay_enabled >> screenshots_enabled;
        if (!(f >> frame_limit)) frame_limit = 144;
        f.close();
    }
}

bool RestartApplication() {
    wchar_t exe_path[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, exe_path, MAX_PATH)) return false;

    wchar_t work_dir[MAX_PATH];
    wcscpy_s(work_dir, exe_path);
    wchar_t* slash = wcsrchr(work_dir, L'\\');
    if (slash) *slash = L'\0';

    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    if (!CreateProcessW(exe_path, nullptr, nullptr, nullptr, FALSE, 0, nullptr, work_dir, &si, &pi)) {
        return false;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    g_restart_requested = true;
    return true;
}

void load_dlls() {
    HMODULE overlay_dll = LoadLibraryA(X("./OverlayDLL.dll"));
    if (overlay_dll) {
        init_overlay = (InitOverlayFunc)GetProcAddress(overlay_dll, X("InitOverlay"));
        update_overlay = (UpdateOverlayFunc)GetProcAddress(overlay_dll, X("UpdateOverlay"));
        overlay_cleanup = (CleanupFunc)GetProcAddress(overlay_dll, X("Cleanup"));
    }
}

void PrintMenu() {
    system(X("cls"));
    if (!g_driver_status.empty()) {
        std::cout << g_driver_status << std::endl;
    }
    std::cout << X("=====================================================") << std::endl;
    std::cout << X("                INTERNAL SYSTEM LOADED                ") << std::endl;
    std::cout << X("=====================================================") << std::endl;
    std::cout << X(" [NUM /]   Recoil Assist:    ") << (recoil_enabled ? X("ON") : X("OFF")) << std::endl;
    std::cout << X(" [NUM 8]   Triggerbot:       ") << (triggerbot_enabled ? X("ON") : X("OFF")) << std::endl;
    std::cout << X(" [NUM 9]   Trigger Mode:     ") << (trigger_auto_mode ? X("AUTO") : X("SINGLE")) << std::endl;
    std::cout << X(" [NUM 7]   Visual Overlay:   ") << (overlay_enabled ? X("VISIBLE") : X("HIDDEN")) << std::endl;
    std::cout << X(" [NUM *]   Auto Screenshot:  ") << (screenshots_enabled ? X("ON") : X("OFF")) << std::endl;
    std::cout << X("-----------------------------------------------------") << std::endl;
    std::cout << X(" [NUM +/-] Recoil Strength:  ") << recoil_strength << std::endl;
    std::cout << X(" [NUM 1++] Smoothing:        ") << smoothing_val << std::endl;
    std::cout << X(" [NUM 2++] Sensitivity:      ") << aim_sens << std::endl;
    std::cout << X(" [NUM 3++] FOV Radius:       ") << fov_radius << std::endl;
    std::cout << X(" [NUM 4++] Frame Limit:      ") << frame_limit << std::endl;
    std::cout << X(" [NUM 6++] Confidence:       ") << conf_threshold << std::endl;
    std::cout << X(" [NUM 5]   Restart (reload settings.cfg)") << std::endl;
    std::cout << X(" [NUM 0]   Emergency Exit") << std::endl;
    std::cout << X("-----------------------------------------------------") << std::endl;
    std::cout << X(" Hold RMB  Aim / recoil / trigger (needs detections)") << std::endl;
    std::cout << X("=====================================================") << std::endl;
}

DriverConnectResult ConnectVhidDriver() {
    g_driver_status.clear();

    if (!vhid_mouse.Open()) {
        g_driver_status =
            std::string(X("[!] VHID driver not reachable (\\\\.\\VHIDMouse)\n"))
            + X("    Win32 error: ") + std::to_string(vhid_mouse.LastOpenError()) + "\n"
            + X("    Map vhid_mouse_wdm.sys with KDMapper, then start Redock.\n");
        std::cerr << g_driver_status;
        return DriverConnectResult::DeviceNotFound;
    }

    g_driver_status = std::string(X("[+] VHID device connected (\\\\.\\VHIDMouse)\n"));

    if (vhid_mouse.ProbeInjection()) {
        g_driver_status += X("[+] Mouse injection ready (IOCTL OK, mouclass linked)\n");
        return DriverConnectResult::Ok;
    }

    g_driver_status +=
        std::string(X("[!] Device open but injection IOCTL failed\n"))
        + X("    Win32 error: ") + std::to_string(vhid_mouse.LastIoctlError()) + "\n"
        + X("    KDMapper: DriverEntry must run (not --map-only). Same WDM build.\n")
        + X("    mouclass callback not found on this Windows build.\n")
        + X("    Aim/trigger will not move the cursor until this is fixed.\n");
    std::cerr << g_driver_status;
    return DriverConnectResult::InjectionFailed;
}

void SaveCleanScreenshot() {
    HWND hwnd = FindWindowA(NULL, X("simulatedgame"));
    if (!hwnd) return;
    RECT rc; GetClientRect(hwnd, &rc);
    int w = rc.right - rc.left, h = rc.bottom - rc.top;
    if (w <= 0 || h <= 0) return;
    HDC sc = GetDC(hwnd), mem = CreateCompatibleDC(sc);
    HBITMAP hbm = CreateCompatibleBitmap(sc, w, h);
    SelectObject(mem, hbm);
    PrintWindow(hwnd, mem, 3);
    BITMAPINFOHEADER bi = { sizeof(BITMAPINFOHEADER), w, -h, 1, 32, BI_RGB };
    cv::Mat frame(h, w, CV_8UC4);
    GetDIBits(mem, hbm, 0, h, frame.data, (BITMAPINFO*)&bi, DIB_RGB_COLORS);
    auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    struct tm t; localtime_s(&t, &now);
    char buf[80]; strftime(buf, sizeof(buf), "%Y-%m-%d_%H-%M-%S", &t);
    std::string fn = SCREENSHOT_DIR + "/" + X("R6_IMG_") + std::string(buf) + "_" + std::to_string(rand() % 1000) + ".jpg";
    cv::Mat bgr; cv::cvtColor(frame, bgr, cv::COLOR_BGRA2BGR);
    cv::imwrite(fn, bgr);
    DeleteObject(hbm); DeleteDC(mem); ReleaseDC(hwnd, sc);
}

class DXGICapture {
private:
    ID3D11Device* Device = nullptr;
    ID3D11DeviceContext* Context = nullptr;
    IDXGIOutputDuplication* Duplication = nullptr;
    ID3D11Texture2D* StagingTex = nullptr;
public:
    DXGICapture() { Init(); }
    ~DXGICapture() { Cleanup(); }
    void Init() {
        Cleanup();
        D3D_FEATURE_LEVEL fl;
        D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &Device, &fl, &Context);
        IDXGIDevice* dxgiD; Device->QueryInterface(__uuidof(IDXGIDevice), (void**)&dxgiD);
        IDXGIAdapter* dxgiA; dxgiD->GetParent(__uuidof(IDXGIAdapter), (void**)&dxgiA);
        IDXGIOutput* dxgiO; dxgiA->EnumOutputs(0, &dxgiO);
        IDXGIOutput1* dxgiO1; dxgiO->QueryInterface(__uuidof(IDXGIOutput1), (void**)&dxgiO1);
        dxgiO1->DuplicateOutput(Device, &Duplication);
        dxgiO1->Release(); dxgiO->Release(); dxgiA->Release(); dxgiD->Release();
    }
    bool Capture(cv::Mat& out, cv::Rect roi) {
        if (!Duplication) return false;
        IDXGIResource* res = nullptr;
        DXGI_OUTDUPL_FRAME_INFO info{};
        if (FAILED(Duplication->AcquireNextFrame(0, &info, &res))) return false;
        ID3D11Texture2D* tex = nullptr;
        if (FAILED(res->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&tex))) {
            res->Release();
            Duplication->ReleaseFrame();
            return false;
        }
        if (!StagingTex) {
            D3D11_TEXTURE2D_DESC d{};
            tex->GetDesc(&d);
            d.Width = (UINT)roi.width;
            d.Height = (UINT)roi.height;
            d.BindFlags = 0;
            d.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
            d.Usage = D3D11_USAGE_STAGING;
            d.MiscFlags = 0;
            Device->CreateTexture2D(&d, nullptr, &StagingTex);
        }
        if (out.rows != roi.height || out.cols != roi.width || out.type() != CV_8UC4) {
            out.create(roi.height, roi.width, CV_8UC4);
        }
        const D3D11_BOX box = {
            (UINT)roi.x, (UINT)roi.y, 0,
            (UINT)(roi.x + roi.width), (UINT)(roi.y + roi.height), 1
        };
        Context->CopySubresourceRegion(StagingTex, 0, 0, 0, 0, tex, 0, &box);
        D3D11_MAPPED_SUBRESOURCE map{};
        bool ok = false;
        if (SUCCEEDED(Context->Map(StagingTex, 0, D3D11_MAP_READ, 0, &map))) {
            const cv::Mat view(roi.height, roi.width, CV_8UC4, map.pData, map.RowPitch);
            view.copyTo(out);
            Context->Unmap(StagingTex, 0);
            ok = true;
        }
        tex->Release();
        res->Release();
        Duplication->ReleaseFrame();
        return ok;
    }
    void ResetStagingTexture() {
        if (StagingTex) {
            StagingTex->Release();
            StagingTex = nullptr;
        }
    }
    void Cleanup() {
        if (Duplication) Duplication->Release();
        ResetStagingTexture();
        if (Context) Context->Release();
        if (Device) Device->Release();
        Duplication = nullptr;
        Context = nullptr;
        Device = nullptr;
    }
};

class AIMBot {
private:
    Ort::Env env;
    std::unique_ptr<Ort::Session> session;
    DXGICapture cap;
    cv::Rect roi;
    int screen_w, screen_h;
    int fov_diameter = 0;
    float fov_scale = 1.0f;
    float last_inference_ms = 0.0f;
    std::vector<float> blob_data;
    cv::Mat resized_bgra;
    std::vector<int> overlay_packet;
    uint64_t result_version = 0;
    uint64_t last_overlay_version = 0;
    std::vector<int> settings_packet = {
        -1, 7, 0, 0, 0, 0,
        -1, 1, 0, 0, 0, 0,
        -1, 2, 0, 0, 0, 0,
        -1, 3, 0, 0, 0, 0,
        -1, 4, 0, 0, 0, 0,
        -1, 6, 0, 0, 0, 0,
        -1, 10, 0, 0, 0, 0,
        -1, 11, 0, 0, 0, 0,
        -2, 0, 0, 0, 0, 0
    };
    std::vector<int64_t> input_shape = { 1, 3, MODEL_SIZE, MODEL_SIZE };
    const char* input_names[1] = { "images" };
    const char* output_names[1] = { "output0" };
    Ort::MemoryInfo memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::RunOptions run_options;
    bool overlay_initialized = false;

    void SyncFovMetrics() {
        fov_diameter = fov_radius * 2;
        fov_scale = (float)fov_diameter / (float)MODEL_SIZE;
    }

    void EnsureFrameBuffers() {
        bufferA.create(fov_diameter, fov_diameter, CV_8UC4);
        bufferB.create(fov_diameter, fov_diameter, CV_8UC4);
    }

    static void BgraToPlanarTensor(const cv::Mat& bgra, float* dst) {
        const int plane = MODEL_SIZE * MODEL_SIZE;
        const uchar* base = bgra.ptr<uchar>(0);
        const int step = (int)bgra.step;
        float* r_plane = dst;
        float* g_plane = dst + plane;
        float* b_plane = dst + plane * 2;
        for (int y = 0; y < MODEL_SIZE; ++y) {
            const uchar* row = base + y * step;
            const int row_base = y * MODEL_SIZE;
            for (int x = 0; x < MODEL_SIZE; ++x) {
                const uchar* px = row + x * 4;
                const int idx = row_base + x;
                r_plane[idx] = px[2] * kInv255;
                g_plane[idx] = px[1] * kInv255;
                b_plane[idx] = px[0] * kInv255;
            }
        }
    }

public:
    AIMBot() : env(ORT_LOGGING_LEVEL_WARNING, X("Aimbot")) {
        LoadConfig();
        SetConsoleTitleA(GenerateRandomString(16).c_str());
        SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE);
        if (!fs::exists(SCREENSHOT_DIR)) fs::create_directory(SCREENSHOT_DIR);
        blob_data.resize(3 * MODEL_SIZE * MODEL_SIZE);
        Ort::SessionOptions opt;
        opt.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        opt.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
        opt.EnableMemPattern();
        opt.EnableCpuMemArena();
        OrtSessionOptionsAppendExecutionProvider_DML(opt, 0);
        try { session = std::make_unique<Ort::Session>(env, MODEL_PATH.c_str(), opt); }
        catch (...) {
            std::cerr << X("[!] Failed to load model: ") << std::string(MODEL_PATH.begin(), MODEL_PATH.end()) << std::endl;
            std::cerr << X("    Place best_fp16.onnx next to Redock.exe and retry.") << std::endl;
            WaitForContinue(X("Press Enter to exit..."));
            exit(1);
        }
        screen_w = GetSystemMetrics(SM_CXSCREEN);
        screen_h = GetSystemMetrics(SM_CYSCREEN);
        UpdateROI();
        PushAllSettings();
        PrintMenu();
    }

    void UpdateROI() {
        SyncFovMetrics();
        roi = cv::Rect(screen_w / 2 - fov_radius, screen_h / 2 - fov_radius, fov_diameter, fov_diameter);
        EnsureFrameBuffers();
        cap.ResetStagingTexture();
        if (!overlay_initialized && init_overlay) {
            init_overlay(roi.x, roi.y, fov_radius);
            overlay_initialized = true;
        }
        PushAllSettings();
    }

    void PushAllSettings() {
        settings_packet[2] = (int)overlay_enabled;
        settings_packet[8] = (int)recoil_enabled;
        settings_packet[14] = (int)triggerbot_enabled;
        settings_packet[20] = (int)trigger_auto_mode;
        settings_packet[26] = (int)screenshots_enabled;
        settings_packet[32] = (int)(recoil_strength * 10);
        settings_packet[38] = (int)show_distance;
        settings_packet[44] = (int)show_confidence;
        settings_packet[49] = (int)(smoothing_val * 100);
        settings_packet[50] = (int)(aim_sens * 100);
        settings_packet[51] = fov_radius;
        settings_packet[52] = (int)(conf_threshold * 100);
        if (update_overlay) update_overlay(settings_packet.data(), (int)settings_packet.size(), 0.0f);
    }

    void capture_thread() {
        while (running) {
            if (!g_ai_active.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_for(std::chrono::milliseconds(16));
                continue;
            }
            {
                std::lock_guard<std::mutex> lock(frame_mtx);
                if (frame_ready) {
                    std::this_thread::yield();
                    continue;
                }
            }
            if (!cap.Capture(*write_buf, roi)) {
                std::this_thread::yield();
                continue;
            }
            {
                std::lock_guard<std::mutex> lock(frame_mtx);
                std::swap(write_buf, read_buf);
                frame_ready = true;
            }
            frame_cv.notify_one();
        }
    }

    void inference_thread() {
        cv::Mat local_frame;
        while (running) {
            if (!g_ai_active.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_for(std::chrono::milliseconds(16));
                continue;
            }
            {
                std::unique_lock<std::mutex> lock(frame_mtx);
                frame_cv.wait(lock, [] { return frame_ready || !running; });
                if (!running) break;
                std::swap(local_frame, *read_buf);
                frame_ready = false;
            }
            auto start = std::chrono::steady_clock::now();
            cv::resize(local_frame, resized_bgra, cv::Size(MODEL_SIZE, MODEL_SIZE), 0, 0, cv::INTER_LINEAR);
            BgraToPlanarTensor(resized_bgra, blob_data.data());
            Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
                memory_info, blob_data.data(), blob_data.size(), input_shape.data(), input_shape.size());
            auto outputs = session->Run(run_options, input_names, &input_tensor, 1, output_names, 1);
            const float* raw = outputs[0].GetTensorData<float>();
            const auto out_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
            const int num_rows = (int)out_shape[1];
            const int num_cols = (int)out_shape[2];
            const float scale = fov_scale;
            const float conf_min = conf_threshold;
            const size_t stride = (size_t)num_cols;

            DetectionResult res;
            res.overlay_data.reserve(192);
            res.candidates.reserve(32);
            for (int i = 0; i < num_cols; ++i) {
                float conf = raw[4 * stride + (size_t)i];
                for (int j = 5; j < num_rows; ++j) {
                    const float v = raw[(size_t)j * stride + (size_t)i];
                    if (v > conf) conf = v;
                }
                if (conf <= conf_min) continue;

                const int px = (int)(raw[(size_t)i] * scale);
                const int py = (int)(raw[stride + (size_t)i] * scale);
                const int bw = (int)(raw[2 * stride + (size_t)i] * scale);
                const int bh = (int)(raw[3 * stride + (size_t)i] * scale);
                const int half_w = bw / 2;
                const int half_h = bh / 2;
                res.overlay_data.push_back(px - half_w);
                res.overlay_data.push_back(py - half_h);
                res.overlay_data.push_back(px + half_w);
                res.overlay_data.push_back(py + half_h);
                res.overlay_data.push_back((int)(conf * 100.0f));
                res.overlay_data.push_back(1);
                res.candidates.push_back({ px, py, bh, bw, conf });
            }
            last_inference_ms = (float)std::chrono::duration_cast<std::chrono::microseconds>(
                std::chrono::steady_clock::now() - start).count() / 1000.0f;
            {
                std::lock_guard<std::mutex> lock(result_mtx);
                shared_result = std::move(res);
                ++result_version;
            }
        }
    }

    void run() {
        std::thread cap_t(&AIMBot::capture_thread, this);
        std::thread inf_t(&AIMBot::inference_thread, this);
        SetThreadPriority(cap_t.native_handle(), THREAD_PRIORITY_ABOVE_NORMAL);
        SetThreadPriority(inf_t.native_handle(), THREAD_PRIORITY_HIGHEST);
        
        auto last_frame_time = std::chrono::steady_clock::now();
        auto last_stat = last_frame_time, last_shot_saved = last_frame_time, last_single = last_frame_time;
        auto last_overlay_stat_update = last_frame_time;
        float overlay_fps = 0.0f;
        float overlay_infer_ms = 0.0f;

        float cur_dx = 0.0f, cur_dy = 0.0f;
        int last_best_x = -1, locked_x = -1, locked_y = -1, frames_lost = 0;

        while (!GetAsyncKeyState(VK_NUMPAD0)) {
            auto loop_start = std::chrono::steady_clock::now();
            float fps = 1000.0f / (float)(std::chrono::duration_cast<std::chrono::milliseconds>(loop_start - last_frame_time).count() + 1);
            last_frame_time = loop_start;

            const bool is_aiming_held = (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0;
            const bool is_shooting_held = (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
            const bool need_ai = overlay_enabled || is_aiming_held;
            g_ai_active.store(need_ai, std::memory_order_relaxed);

            bool change = false;
            if (GetAsyncKeyState(VK_DIVIDE) & 1) { recoil_enabled = !recoil_enabled; change = true; }
            if (GetAsyncKeyState(VK_NUMPAD8) & 1) { triggerbot_enabled = !triggerbot_enabled; change = true; }
            if (GetAsyncKeyState(VK_NUMPAD9) & 1) { trigger_auto_mode = !trigger_auto_mode; change = true; }
            if (GetAsyncKeyState(VK_NUMPAD7) & 1) { overlay_enabled = !overlay_enabled; change = true; }
            if (GetAsyncKeyState(VK_MULTIPLY) & 1) { screenshots_enabled = !screenshots_enabled; change = true; }
            if (GetAsyncKeyState(VK_NUMPAD5) & 1) {
                if (is_auto_firing && vhid_mouse.IsOpen()) {
                    vhid_mouse.Click(2);
                    is_auto_firing = false;
                }
                if (RestartApplication()) {
                    running = false;
                    break;
                }
            }

            bool hold_num1 = GetAsyncKeyState(VK_NUMPAD1) & 0x8000;
            bool hold_num2 = GetAsyncKeyState(VK_NUMPAD2) & 0x8000;
            bool hold_num3 = GetAsyncKeyState(VK_NUMPAD3) & 0x8000;
            bool hold_num4 = GetAsyncKeyState(VK_NUMPAD4) & 0x8000;
            bool hold_num6 = GetAsyncKeyState(VK_NUMPAD6) & 0x8000;
            bool plus = (GetAsyncKeyState(VK_ADD) & 1);
            bool minus = (GetAsyncKeyState(VK_SUBTRACT) & 1);

            if (plus || minus) {
                if (hold_num1) { smoothing_val = std::clamp(smoothing_val + (plus ? 0.05f : -0.05f), 0.05f, 0.95f); change = true; }
                else if (hold_num2) { aim_sens = std::clamp(aim_sens + (plus ? 0.01f : -0.01f), 0.01f, 1.0f); change = true; }
                else if (hold_num3) { fov_radius = std::clamp(fov_radius + (plus ? 10 : -10), 50, 400); UpdateROI(); change = true; }
                else if (hold_num4) { frame_limit = std::clamp(frame_limit + (plus ? 10 : -10), 30, 360); change = true; }
                else if (hold_num6) { conf_threshold = std::clamp(conf_threshold + (plus ? 0.05f : -0.05f), 0.1f, 0.95f); change = true; }
                else { recoil_strength = std::clamp(recoil_strength + (plus ? 0.1f : -0.1f), 0.0f, 5.0f); change = true; }
            }

            if (change) { SaveConfig(); PushAllSettings(); PrintMenu(); }

            const bool overlay_stats_due =
                std::chrono::duration_cast<std::chrono::milliseconds>(loop_start - last_overlay_stat_update).count() >= 1000;
            if (overlay_stats_due) {
                overlay_fps = fps;
                overlay_infer_ms = last_inference_ms;
                last_overlay_stat_update = loop_start;
            }

            TargetCandidate best_target = { -1, -1, 0, 0, 0.0f };
            const std::vector<TargetCandidate>* candidates = nullptr;
            const std::vector<int>* detection_overlay = nullptr;
            uint64_t overlay_version = 0;
            {
                std::lock_guard<std::mutex> lock(result_mtx);
                candidates = &shared_result.candidates;
                detection_overlay = &shared_result.overlay_data;
                overlay_version = result_version;
            }

            const bool need_targeting = is_aiming_held || triggerbot_enabled;
            if (need_targeting) {
                float best_score = 99999.0f;
                const float sticky_dist_sq = STICKY_DISTANCE * STICKY_DISTANCE;
                for (const auto& cand : *candidates) {
                    const float dx_center = (float)(cand.x - fov_radius);
                    const float dy_center = (float)(cand.y - fov_radius);
                    float dist = std::sqrt(dx_center * dx_center + dy_center * dy_center);
                    if (locked_x != -1) {
                        const float dx_lock = (float)(cand.x - locked_x);
                        const float dy_lock = (float)(cand.y - locked_y);
                        const float lock_dist_sq = dx_lock * dx_lock + dy_lock * dy_lock;
                        if (lock_dist_sq < sticky_dist_sq) dist -= TARGET_LOCK_BONUS;
                    }
                    if (dist < best_score) { best_score = dist; best_target = cand; }
                }

                if (best_target.x != -1) { locked_x = best_target.x; locked_y = best_target.y; frames_lost = 0; }
                else if (++frames_lost > MAX_LOST_FRAMES) { locked_x = -1; locked_y = -1; }
            }

            if (overlay_enabled && update_overlay && (overlay_version != last_overlay_version || overlay_stats_due)) {
                const size_t det_count = detection_overlay->size();
                overlay_packet.resize(6 + det_count);
                overlay_packet[0] = 0;
                overlay_packet[1] = 0;
                overlay_packet[2] = 0;
                overlay_packet[3] = 0;
                overlay_packet[4] = (int)std::lround(overlay_infer_ms * 100.0f);
                overlay_packet[5] = 0;
                if (det_count > 0) {
                    memcpy(overlay_packet.data() + 6, detection_overlay->data(), det_count * sizeof(int));
                }
                update_overlay(overlay_packet.data(), (int)overlay_packet.size(), overlay_fps);
                if (overlay_version != last_overlay_version) {
                    last_overlay_version = overlay_version;
                }
            }

            if (is_aiming_held) {
                float final_move_x = 0.0f, final_move_y = 0.0f;
                float aim_dx = 0.0f, aim_dy = 0.0f;

                if (best_target.x != -1) {
                    aim_dx = (float)best_target.x - (float)fov_radius;
                    float head_y = ((float)best_target.y - (best_target.h / 2.0f)) + (best_target.h * PYTHON_AIM_HEIGHT);
                    aim_dy = head_y - (float)fov_radius;
                    float distance = std::sqrt(aim_dx * aim_dx + aim_dy * aim_dy);

                    if (distance > MIN_DIST_THRESHOLD) {
                        // --- ASPECT RATIO DYNAMIC SCALING ---
                        float effective_dim = ((float)best_target.w > ((float)best_target.h * 0.8f)) ? (float)best_target.w : (float)best_target.h / 2.5f;
                        float dist_factor = std::clamp(effective_dim / 35.0f, 0.45f, 1.0f);

                        float dynamic_sens = aim_sens * dist_factor;
                        float dynamic_smoothing = std::clamp(smoothing_val / dist_factor, 0.1f, 0.95f);

                        // --- PREDICTION ---
                        float vel_x = (last_best_x != -1) ? (float)(best_target.x - last_best_x) : 0;
                        last_best_x = best_target.x;

                        float target_dx = (aim_dx + (vel_x * PREDICTION_MULT)) * dynamic_sens;
                        float target_dy = aim_dy * dynamic_sens;

                        cur_dx += (target_dx - cur_dx) * (1.0f - dynamic_smoothing);
                        cur_dy += (target_dy - cur_dy) * (1.0f - dynamic_smoothing);

                        final_move_x = std::clamp(cur_dx, -MAX_MOVE_SPEED, MAX_MOVE_SPEED);
                        final_move_y = std::clamp(cur_dy, -MAX_MOVE_SPEED, MAX_MOVE_SPEED);
                    }
                }
                else { last_best_x = -1; cur_dx *= 0.4f; cur_dy *= 0.4f; }

                if (recoil_enabled && (is_shooting_held || is_auto_firing)) {
                    final_move_y += (6.2f * recoil_strength);
                }

                int move_x = (int)std::lround(final_move_x);
                int move_y = (int)std::lround(final_move_y);

                // Force 1-pixel movement for sub-1.0 results to overcome friction
                if (std::abs(final_move_x) >= 0.5f && move_x == 0) move_x = (final_move_x > 0.0f) ? 1 : -1;
                if (std::abs(final_move_y) >= 0.5f && move_y == 0) move_y = (final_move_y > 0.0f) ? 1 : -1;

                if ((move_x != 0 || move_y != 0) && vhid_mouse.IsOpen()) {
                    vhid_mouse.Move(move_x, move_y);
                }
            }
            else { last_best_x = -1; cur_dx = 0.0f; cur_dy = 0.0f; locked_x = -1; locked_y = -1; }

            // Triggerbot logic
            bool target_in_trigger = false;
            if (best_target.x != -1) {
                const float ty = ((float)best_target.y - (best_target.h * 0.5f)) + (best_target.h * PYTHON_AIM_HEIGHT);
                const float tdx = (float)best_target.x - (float)fov_radius;
                const float tdy = ty - (float)fov_radius;
                target_in_trigger = (tdx * tdx + tdy * tdy) <= 625.0f; // 25px radius
            }

            if (triggerbot_enabled && is_aiming_held && !is_shooting_held) {
                if (trigger_auto_mode) {
                    if (target_in_trigger && !is_auto_firing && vhid_mouse.IsOpen()) { vhid_mouse.Click(1); is_auto_firing = true; }
                    else if (!target_in_trigger && is_auto_firing && vhid_mouse.IsOpen()) { vhid_mouse.Click(2); is_auto_firing = false; }
                }
                else if (target_in_trigger && std::chrono::duration_cast<std::chrono::milliseconds>(loop_start - last_single).count() >= 120) {
                    if (vhid_mouse.IsOpen()) { vhid_mouse.Click(1); std::this_thread::sleep_for(std::chrono::milliseconds(25)); vhid_mouse.Click(2); }
                    last_single = loop_start;
                }
            }
            else if (is_auto_firing && !target_in_trigger) {
                if (vhid_mouse.IsOpen()) vhid_mouse.Click(2);
                is_auto_firing = false;
            }

            if (is_aiming_held && is_shooting_held && screenshots_enabled && std::chrono::duration_cast<std::chrono::seconds>(loop_start - last_shot_saved).count() >= 1) {
                std::thread(SaveCleanScreenshot).detach(); last_shot_saved = loop_start;
            }

            auto loop_end = std::chrono::steady_clock::now();
            auto elapsed = loop_end - loop_start;
            const std::chrono::duration<double, std::milli> frame_duration(1000.0 / (double)frame_limit);
            if (elapsed < frame_duration) std::this_thread::sleep_for(frame_duration - elapsed);
        }
        running = false; frame_cv.notify_all(); cap_t.join(); inf_t.join();
        if (overlay_cleanup) overlay_cleanup();
    }
};

int main() {
    srand((unsigned int)time(NULL));
    timeBeginPeriod(1);
    SetPriorityClass(GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS);
    load_dlls();

    const DriverConnectResult driver_result = ConnectVhidDriver();
    if (driver_result == DriverConnectResult::DeviceNotFound) {
        WaitForContinue(X("Press Enter to exit..."));
        return 1;
    }
    if (driver_result == DriverConnectResult::InjectionFailed) {
        WaitForContinue(X("Press Enter to continue (mouse injection disabled)..."));
    }

    try { AIMBot bot; bot.run(); }
    catch (...) {
        if (!g_restart_requested) {
            std::cerr << X("[!] Redock stopped due to an unexpected error.") << std::endl;
            WaitForContinue(X("Press Enter to exit..."));
        }
    }
    vhid_mouse.Close();
    timeEndPeriod(1);
    return 0;
}