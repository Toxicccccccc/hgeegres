#include "aimassist/serial_bridge.hpp"

#include <Windows.h>

#include <string>

namespace aimassist
{
SerialBridge::~SerialBridge()
{
    close();
}

void SerialBridge::close()
{
    if (handle_ != nullptr && handle_ != INVALID_HANDLE_VALUE)
    {
        CloseHandle(static_cast<HANDLE>(handle_));
    }
    handle_ = nullptr;
    connected_port_.clear();
}

std::string const& SerialBridge::connected_port() const noexcept
{
    return connected_port_;
}

bool SerialBridge::connect(std::string const& port, std::string& status)
{
    if (port == connected_port_ && handle_ != nullptr)
    {
        return true;
    }
    close();
    connected_port_ = port;
    if (port.empty())
    {
        status = "Arduino port is empty";
        return false;
    }

    auto const path = port.rfind("\\\\.\\", 0) == 0 ? port : "\\\\.\\" + port;
    auto* handle = CreateFileA(
        path.c_str(),
        GENERIC_WRITE,
        0,
        nullptr,
        OPEN_EXISTING,
        0,
        nullptr
    );
    if (handle == INVALID_HANDLE_VALUE)
    {
        auto const code = GetLastError();
        // ERROR_FILE_NOT_FOUND (2) means the port name does not exist on this
        // machine; ERROR_ACCESS_DENIED (5) usually means another program (or a
        // previous session) already holds it open. Say which, so the fix is
        // obvious, and leave the engine running without input output either way.
        std::string hint = "the port does not exist";
        if (code == ERROR_ACCESS_DENIED)
        {
            hint = "the port is busy - close the other program using it";
        }
        status = "Arduino error on " + port + ": could not open the port (" + hint
            + ", Windows error " + std::to_string(code) + ") - running without input output";
        connected_port_ = port;
        return false;
    }

    DCB dcb{};
    dcb.DCBlength = sizeof(DCB);
    if (!GetCommState(handle, &dcb))
    {
        CloseHandle(handle);
        status = "Arduino error on " + port + ": GetCommState failed";
        return false;
    }
    // 115200 matches the firmware's SERIAL_BAUD. The previous 9600 rate spent
    // ~8ms per 8-byte packet on the wire, a hard floor on input latency; the
    // packet format is unchanged, only the line speed.
    dcb.BaudRate = CBR_115200;
    dcb.ByteSize = 8;
    dcb.Parity = NOPARITY;
    dcb.StopBits = ONESTOPBIT;
    dcb.fBinary = TRUE;
    if (!SetCommState(handle, &dcb))
    {
        CloseHandle(handle);
        status = "Arduino error on " + port + ": SetCommState failed";
        return false;
    }

    COMMTIMEOUTS timeouts{};
    timeouts.WriteTotalTimeoutConstant = 0;
    timeouts.WriteTotalTimeoutMultiplier = 0;
    SetCommTimeouts(handle, &timeouts);

    handle_ = handle;
    status = "Arduino connected on " + port;
    return true;
}

bool SerialBridge::send_adjustment(int x, int y, bool click)
{
    if (handle_ == nullptr || handle_ == INVALID_HANDLE_VALUE)
    {
        return false;
    }
    auto const payload = std::to_string(x) + "," + std::to_string(y) + ","
        + (click ? "1" : "0") + "*";
    DWORD written = 0;
    return WriteFile(
        static_cast<HANDLE>(handle_),
        payload.data(),
        static_cast<DWORD>(payload.size()),
        &written,
        nullptr
    ) == TRUE;
}
} // namespace aimassist
