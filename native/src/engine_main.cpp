#include "aimassist/engine.hpp"
#include "aimassist/settings.hpp"

#include <Windows.h>

#include <atomic>
#include <exception>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>

namespace
{
std::atomic_bool g_stop{false};

BOOL WINAPI console_handler(DWORD control)
{
    if (control == CTRL_C_EVENT || control == CTRL_BREAK_EVENT || control == CTRL_CLOSE_EVENT)
    {
        g_stop.store(true);
        return TRUE;
    }
    return FALSE;
}

std::filesystem::path default_config_path()
{
    auto const cwd = std::filesystem::current_path() / "disabledassistance_config.json";
    if (std::filesystem::exists(cwd))
    {
        return cwd;
    }
    auto const parent = std::filesystem::current_path().parent_path() / "disabledassistance_config.json";
    if (std::filesystem::exists(parent))
    {
        return parent;
    }
    return cwd;
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        // Keep diagnostics visible even when stdout is redirected: the engine
        // must never appear to hang silently during a capture or CUDA stall.
        std::cout.setf(std::ios::unitbuf);
        std::cerr.setf(std::ios::unitbuf);
        SetConsoleCtrlHandler(console_handler, TRUE);
        std::filesystem::path config_path = default_config_path();
        std::optional<std::uint64_t> frame_limit;
        for (int index = 1; index < argc; ++index)
        {
            std::string const argument = argv[index];
            if (argument == "--frames" && index + 1 < argc)
            {
                frame_limit = static_cast<std::uint64_t>(std::stoull(argv[++index]));
            }
            else if (argument == "--help")
            {
                std::cout << "Usage: native_engine [settings.json] [--frames N]\n";
                return 0;
            }
            else if (!argument.empty() && argument[0] != '-')
            {
                config_path = argument;
            }
            else
            {
                std::cerr << "Unknown argument: " << argument << '\n';
                return 2;
            }
        }

        auto settings = aimassist::load_settings(config_path.string());
        if (settings.model_path.empty())
        {
            std::cerr << "settings.json must include model_path pointing at a .engine file.\n";
            return 2;
        }
        std::cout << "Using settings: " << config_path.string() << '\n';
        // Hand the engine the config path so it can re-read live-tunable keys
        // (the preview stream) if the GUI rewrites the file while it runs.
        aimassist::NativeEngine engine(std::move(settings), config_path.string());
        engine.run(g_stop, frame_limit);
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "Native engine failed: " << error.what() << '\n';
        return 1;
    }
}
