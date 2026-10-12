#pragma once

#include <string>

namespace aimassist
{
class SerialBridge
{
public:
    SerialBridge() = default;
    ~SerialBridge();

    SerialBridge(SerialBridge const&) = delete;
    SerialBridge& operator=(SerialBridge const&) = delete;

    bool connect(std::string const& port, std::string& status);
    bool send_adjustment(int x, int y, bool click);
    void close();
    std::string const& connected_port() const noexcept;

private:
    void* handle_{};
    std::string connected_port_;
};
} // namespace aimassist
