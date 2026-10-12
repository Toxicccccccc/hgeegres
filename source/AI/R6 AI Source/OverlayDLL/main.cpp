#include <windows.h>
#include <vector>
#include <string>
#include <map>
#include <gdiplus.h>
#include <time.h>
#include <algorithm>

#pragma comment (lib, "Gdiplus.lib")
using namespace Gdiplus;

struct Box {
    int x1, y1, x2, y2;
    float confidence;
    float distance;
    bool isTarget;
};

struct TimedNotif {
    std::wstring text;
    DWORD expiry;
    DWORD startTime;
};

// --- GLOBAL STATE ---
std::vector<Box> g_boxes;
std::vector<float> g_smoothedConf;
std::vector<float> g_smoothedDist;
std::map<int, TimedNotif> g_notifs;
HWND g_hwnd = NULL;
int g_fovRadius = 0;
float g_curFPS = 0;
float g_curMS = 0;
ULONG_PTR gdiplusToken;
bool g_classRegistered = false;
std::wstring g_randomClassName;
FontFamily* g_fontFamily = nullptr;
Font* g_font = nullptr;
Font* g_statsFont = nullptr;
Font* g_labelFont = nullptr;
HDC g_memDC = nullptr;
HBITMAP g_memBitmap = nullptr;
int g_memBitmapW = 0;
int g_memBitmapH = 0;
HBRUSH g_blackBrush = nullptr;
Pen* g_fovPen = nullptr;
SolidBrush* g_purpleBrush = nullptr;
SolidBrush* g_whiteBrush = nullptr;
SolidBrush* g_bgBrush = nullptr;
wchar_t g_statsText[64] = L"";

// State tracking to prevent notification spam
int last_sm = -1, last_sn = -1, last_fov = -1, last_conf = -1;
bool g_showConfidence = true;
bool g_showDistance = true;

std::wstring GenerateRandomString(int len) {
    std::wstring str;
    str.reserve((size_t)len);
    static const wchar_t charset[] = L"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    for (int i = 0; i < len; ++i)
        str += charset[rand() % (sizeof(charset) / sizeof(wchar_t) - 1)];
    return str;
}

void EnsureOverlayFonts() {
    if (g_fontFamily) return;
    g_fontFamily = new FontFamily(L"Segoe UI");
    g_font = new Font(g_fontFamily, 9, FontStyleBold, UnitPoint);
    g_statsFont = new Font(g_fontFamily, 8, FontStyleRegular, UnitPoint);
    g_labelFont = new Font(g_fontFamily, 8, FontStyleBold, UnitPoint);
    g_blackBrush = CreateSolidBrush(RGB(0, 0, 0));
    g_fovPen = new Pen(Color(120, 191, 64, 255), 1.0f);
    REAL dashValues[2] = { 15.0f, 10.0f };
    g_fovPen->SetDashPattern(dashValues, 2);
    g_purpleBrush = new SolidBrush(Color(255, 191, 64, 255));
    g_whiteBrush = new SolidBrush(Color(255, 255, 255, 255));
    g_bgBrush = new SolidBrush(Color(180, 15, 15, 15));
}

void ReleaseOverlayFonts() {
    delete g_labelFont; g_labelFont = nullptr;
    delete g_statsFont; g_statsFont = nullptr;
    delete g_font; g_font = nullptr;
    delete g_fontFamily; g_fontFamily = nullptr;
    delete g_fovPen; g_fovPen = nullptr;
    delete g_purpleBrush; g_purpleBrush = nullptr;
    delete g_whiteBrush; g_whiteBrush = nullptr;
    delete g_bgBrush; g_bgBrush = nullptr;
    if (g_blackBrush) {
        DeleteObject(g_blackBrush);
        g_blackBrush = nullptr;
    }
}

void ReleaseMemBitmap() {
    if (g_memBitmap) {
        DeleteObject(g_memBitmap);
        g_memBitmap = nullptr;
    }
    if (g_memDC) {
        DeleteDC(g_memDC);
        g_memDC = nullptr;
    }
    g_memBitmapW = 0;
    g_memBitmapH = 0;
}

void DrawOverlay(HDC hdc) {
    Graphics graphics(hdc);
    graphics.Clear(Color(0, 0, 0, 0));
    graphics.SetSmoothingMode(SmoothingModeAntiAlias);
    graphics.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
    EnsureOverlayFonts();

    const int diameter = g_fovRadius * 2;
    graphics.DrawEllipse(g_fovPen, 1, 1, diameter - 2, diameter - 2);

    swprintf_s(g_statsText, L"FPS: %d  [ AI: %.1fms ]", (int)g_curFPS, g_curMS);
    const int statsY = diameter - 35;
    graphics.FillRectangle(g_bgBrush, 10, statsY, 130, 18);
    graphics.FillRectangle(g_purpleBrush, 10, statsY, 2, 18);
    graphics.DrawString(g_statsText, -1, g_statsFont, PointF(15.0f, (float)statsY - 2), g_whiteBrush);

    const Color mainPurple(255, 191, 64, 255);

    // 3. Notifications
    DWORD now = GetTickCount();
    int yOffset = 30;
    for (auto it = g_notifs.begin(); it != g_notifs.end(); ) {
        if (now > it->second.expiry) { it = g_notifs.erase(it); }
        else {
            long long remaining = (long long)it->second.expiry - now;
            int alpha = (remaining < 1000) ? (int)((remaining * 255) / 1000) : 255;
            alpha = std::clamp(alpha, 0, 255);
            SolidBrush animPurple(Color(alpha, 191, 64, 255));
            SolidBrush animBg(Color((alpha * 160) / 255, 15, 15, 15));
            graphics.FillRectangle(&animBg, (g_fovRadius * 2) - 140, yOffset, 120, 22);
            graphics.FillRectangle(&animPurple, (g_fovRadius * 2) - 22, yOffset, 2, 22);
            graphics.DrawString(it->second.text.c_str(), -1, g_font, PointF((float)(g_fovRadius * 2) - 135, (float)yOffset + 3), &animPurple);
            yOffset += 26; ++it;
        }
    }

    // 4. Detection Boxes
    for (size_t i = 0; i < g_boxes.size(); ++i) {
        const auto& b = g_boxes[i];
        Color bCol = b.isTarget ? mainPurple : Color(200, 255, 255, 255);
        Pen pen(bCol, 1.0f);
        int boxW = b.x2 - b.x1;
        int l = boxW / 4;

        graphics.DrawLine(&pen, b.x1, b.y1, b.x1 + l, b.y1);
        graphics.DrawLine(&pen, b.x1, b.y1, b.x1, b.y1 + l);
        graphics.DrawLine(&pen, b.x2, b.y2, b.x2 - l, b.y2);
        graphics.DrawLine(&pen, b.x2, b.y2, b.x2, b.y2 - l);

        if (i >= g_smoothedConf.size()) g_smoothedConf.resize(i + 1, b.confidence);
        else g_smoothedConf[i] += (b.confidence - g_smoothedConf[i]) * 0.05f;

        if (i >= g_smoothedDist.size()) g_smoothedDist.resize(i + 1, b.distance);
        else g_smoothedDist[i] += (b.distance - g_smoothedDist[i]) * 0.05f;

        if (g_showConfidence) {
            std::wstring confStr = std::to_wstring((int)g_smoothedConf[i]) + L"%";
            RectF textRect;
            graphics.MeasureString(confStr.c_str(), -1, g_labelFont, PointF(0, 0), &textRect);
            graphics.FillRectangle(g_bgBrush, (float)b.x1, (float)b.y1 - textRect.Height - 6, textRect.Width + 4, textRect.Height);
            graphics.DrawString(confStr.c_str(), -1, g_labelFont, PointF((float)b.x1 + 2, (float)b.y1 - textRect.Height - 6), g_whiteBrush);
        }

        if (g_showDistance) {
            std::wstring distStr = std::to_wstring((int)g_smoothedDist[i]) + L"m";
            RectF textRect;
            graphics.MeasureString(distStr.c_str(), -1, g_labelFont, PointF(0, 0), &textRect);
            float centerX = b.x1 + (boxW / 2.0f) - (textRect.Width / 2.0f);
            graphics.FillRectangle(g_bgBrush, centerX - 2, (float)b.y2 + 6, textRect.Width + 4, textRect.Height);
            graphics.DrawString(distStr.c_str(), -1, g_labelFont, PointF(centerX, (float)b.y2 + 6), g_purpleBrush);
        }
    }
}

LRESULT CALLBACK WndProcedure(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    if (uMsg == WM_PAINT) {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);
        const int w = g_fovRadius * 2;
        const int h = g_fovRadius * 2;
        if (!g_memDC || g_memBitmapW != w || g_memBitmapH != h) {
            ReleaseMemBitmap();
            g_memDC = CreateCompatibleDC(hdc);
            g_memBitmap = CreateCompatibleBitmap(hdc, w, h);
            SelectObject(g_memDC, g_memBitmap);
            g_memBitmapW = w;
            g_memBitmapH = h;
        }
        EnsureOverlayFonts();
        RECT r = { 0, 0, w, h };
        FillRect(g_memDC, &r, g_blackBrush);
        DrawOverlay(g_memDC);
        BitBlt(hdc, 0, 0, w, h, g_memDC, 0, 0, SRCCOPY);
        EndPaint(hWnd, &ps);
        return 0;
    }
    return DefWindowProc(hWnd, uMsg, wParam, lParam);
}

extern "C" {
    __declspec(dllexport) void InitOverlay(int x, int y, int radius) {
        if (g_hwnd) {
            DestroyWindow(g_hwnd);
            g_hwnd = NULL;
        }
        g_boxes.clear();
        g_smoothedConf.clear();
        g_smoothedDist.clear();
        g_notifs.clear();
        last_sm = last_sn = last_fov = last_conf = -1;
        ReleaseMemBitmap();

        srand((unsigned int)time(NULL));
        g_fovRadius = radius;
        if (!g_classRegistered) {
            GdiplusStartupInput gdiplusStartupInput;
            GdiplusStartup(&gdiplusToken, &gdiplusStartupInput, NULL);
            EnsureOverlayFonts();
            g_randomClassName = GenerateRandomString(12);
            WNDCLASS wc = { 0 };
            wc.lpfnWndProc = WndProcedure;
            wc.hInstance = GetModuleHandle(NULL);
            wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
            wc.lpszClassName = g_randomClassName.c_str();
            RegisterClass(&wc);
            g_classRegistered = true;
        }
        g_hwnd = CreateWindowEx(WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_COMPOSITED,
            g_randomClassName.c_str(), GenerateRandomString(8).c_str(), WS_POPUP, x, y, radius * 2, radius * 2, NULL, NULL, GetModuleHandle(NULL), NULL);
        SetLayeredWindowAttributes(g_hwnd, RGB(0, 0, 0), 255, LWA_COLORKEY);
        SetWindowPos(g_hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
    }

    __declspec(dllexport) void UpdateOverlay(int* data, int count, float fps) {
        if (!g_hwnd) return;

        g_boxes.clear();
        g_boxes.reserve(32);
        DWORD now = GetTickCount();
        DWORD expiryTime = now + 2500;

        for (int i = 0; i + 5 < count; i += 6) {
            // Packet -2: Sync Settings (With Change Detection)
            if (data[i] == -2) {
                int sm = data[i + 1], sn = data[i + 2], fov = data[i + 3], conf = data[i + 4];

                if (fov != last_fov) {
                    g_fovRadius = fov; last_fov = fov;
                    int screen_w = GetSystemMetrics(SM_CXSCREEN);
                    int screen_h = GetSystemMetrics(SM_CYSCREEN);
                    SetWindowPos(g_hwnd, HWND_TOPMOST, screen_w / 2 - g_fovRadius, screen_h / 2 - g_fovRadius, g_fovRadius * 2, g_fovRadius * 2, SWP_NOACTIVATE);
                    g_notifs[103] = { L"FOV: " + std::to_wstring(fov), expiryTime, now };
                }

                if (sm != last_sm) {
                    last_sm = sm;
                    g_notifs[101] = { L"SMOOTH: 0." + std::to_wstring(sm), expiryTime, now };
                }
                if (sn != last_sn) {
                    last_sn = sn;
                    g_notifs[102] = { L"SENS: 0." + std::to_wstring(sn), expiryTime, now };
                }
                if (conf != last_conf) {
                    last_conf = conf;
                    g_notifs[104] = { L"CONF: " + std::to_wstring(conf) + L"%", expiryTime, now };
                }
            }
            else if (data[i] == -1) {
                int id = data[i + 1], val = data[i + 2];
                if (id == 7) ShowWindow(g_hwnd, val ? SW_SHOWNOACTIVATE : SW_HIDE);
                if (id == 10) g_showDistance = (val != 0);
                if (id == 11) g_showConfidence = (val != 0);

                std::wstring txt;
                if (id == 1) txt = (val ? L"RECOIL: ON" : L"RECOIL: OFF");
                else if (id == 2) txt = (val ? L"TRIG: ON" : L"TRIG: OFF");
                else if (id == 3) txt = (val ? L"MODE: AUTO" : L"MODE: SINGLE");
                else if (id == 4) txt = (val ? L"SHOTS: ON" : L"SHOTS: OFF");
                else if (id == 6) txt = L"STR: " + std::to_wstring(val / 10) + L"." + std::to_wstring(val % 10);

                if (!txt.empty()) g_notifs[id] = { txt, expiryTime, now };
            }
            else {
                // Latency and Box Data
                if (data[i] == 0 && data[i + 1] == 0 && data[i + 5] == 0) {
                    g_curFPS = fps;
                    g_curMS = (float)data[i + 4] / 100.0f;
                }
                else {
                    float boxHeight = (float)(data[i + 3] - data[i + 1]);
                    float estimatedDist = (boxHeight > 0) ? (920.0f / boxHeight) : 0.0f;
                    g_boxes.push_back({ data[i], data[i + 1], data[i + 2], data[i + 3], (float)data[i + 4], estimatedDist, (bool)data[i + 5] });
                }
            }
        }

        if (g_smoothedConf.size() > g_boxes.size()) g_smoothedConf.resize(g_boxes.size());
        if (g_smoothedDist.size() > g_boxes.size()) g_smoothedDist.resize(g_boxes.size());

        MSG msg;
        while (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) break;
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }
        RedrawWindow(g_hwnd, NULL, NULL, RDW_INVALIDATE | RDW_NOERASE | RDW_NOCHILDREN);
    }

    __declspec(dllexport) void Cleanup() {
        if (g_hwnd) {
            DestroyWindow(g_hwnd);
            g_hwnd = NULL;
        }
        ReleaseMemBitmap();
        g_boxes.clear();
        g_smoothedConf.clear();
        g_smoothedDist.clear();
        g_notifs.clear();
        g_fovRadius = 0;
        last_sm = last_sn = last_fov = last_conf = -1;
        if (g_classRegistered) {
            UnregisterClass(g_randomClassName.c_str(), GetModuleHandle(NULL));
            g_classRegistered = false;
        }
        ReleaseOverlayFonts();
        if (gdiplusToken) {
            GdiplusShutdown(gdiplusToken);
            gdiplusToken = 0;
        }
    }
}