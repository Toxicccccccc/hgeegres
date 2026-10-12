#include "aimassist/input.hpp"

#include <Windows.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <exception>
#include <string>
#include <unordered_map>

namespace
{
int virtual_key_for(std::string const& input_name)
{
    // The GUI has two spellings for the same buttons: the engine's own names
    // ("Left mouse") and the schema/keybind names ("Left Mouse", "Mouse 4 (X1)").
    // Accept both so a lock/shoot key chosen on any page resolves to the same VK.
    static std::unordered_map<std::string, int> const mouse_buttons{
        {"left mouse", VK_LBUTTON},
        {"right mouse", VK_RBUTTON},
        {"middle mouse", VK_MBUTTON},
        {"mouse 4", VK_XBUTTON1},
        {"mouse 4 (x1)", VK_XBUTTON1},
        {"mouse 5", VK_XBUTTON2},
        {"mouse 5 (x2)", VK_XBUTTON2},
    };
    auto normalized = input_name;
    for (auto& character : normalized)
    {
        character = static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
    }
    auto const mouse = mouse_buttons.find(normalized);
    if (mouse != mouse_buttons.end())
    {
        return mouse->second;
    }

    // A numeric binding is a raw Windows virtual-key code. The GUI's keybind
    // control stores the VK as an integer (for example 0x05 for Mouse 4), and the
    // native config bridge writes it as a decimal string; without this the lock
    // key never matched and the assistant never moved or clicked.
    if (!normalized.empty()
        && std::all_of(normalized.begin(), normalized.end(), [](char c) {
               return std::isdigit(static_cast<unsigned char>(c)) != 0;
           }))
    {
        try
        {
            auto const code = std::stol(normalized);
            if (code > 0 && code < 256)
            {
                return static_cast<int>(code);
            }
        }
        catch (std::exception const&)
        {
        }
    }

    std::string key = input_name;
    for (auto& character : key)
    {
        character = static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
    }

    static std::unordered_map<std::string, int> const special_keys{
        {"alt", VK_MENU},
        {"ctrl", VK_CONTROL},
        {"shift", VK_SHIFT},
        {"space", VK_SPACE},
        {"tab", VK_TAB},
        {"enter", VK_RETURN},
        {"esc", VK_ESCAPE},
        {"backspace", VK_BACK},
        {"caps lock", VK_CAPITAL},
        {"delete", VK_DELETE},
        {"down", VK_DOWN},
        {"end", VK_END},
        {"home", VK_HOME},
        {"insert", VK_INSERT},
        {"left", VK_LEFT},
        {"menu", VK_APPS},
        {"page down", VK_NEXT},
        {"page up", VK_PRIOR},
        {"pause", VK_PAUSE},
        {"print screen", VK_SNAPSHOT},
        {"right", VK_RIGHT},
        {"scroll lock", VK_SCROLL},
        {"up", VK_UP},
        {"windows", VK_LWIN},
    };
    auto const special = special_keys.find(key);
    if (special != special_keys.end())
    {
        return special->second;
    }
    if (key.size() == 1 && key[0] >= 32 && key[0] <= 126)
    {
        return static_cast<int>(std::toupper(static_cast<unsigned char>(key[0])));
    }
    if (key.size() >= 2 && key[0] == 'f')
    {
        try
        {
            auto const number = std::stoi(key.substr(1));
            if (number >= 1 && number <= 24)
            {
                return VK_F1 + number - 1;
            }
        }
        catch (std::exception const&)
        {
        }
    }
    return 0;
}
} // namespace

namespace aimassist
{
bool input_is_pressed(std::string const& input_name)
{
    if (input_name == "Auto")
    {
        return true;
    }
    auto const virtual_key = virtual_key_for(input_name);
    if (virtual_key == 0)
    {
        return false;
    }
    return (GetAsyncKeyState(virtual_key) & 0x8000) != 0;
}

int resolve_input_key(std::string const& input_name)
{
    // "Auto" (always held) has no key code; report 0 and let the caller treat
    // that as "always pressed" via input_is_pressed_vk().
    return virtual_key_for(input_name);
}

bool input_is_pressed_vk(int virtual_key)
{
    if (virtual_key == 0)
    {
        return false;
    }
    return (GetAsyncKeyState(virtual_key) & 0x8000) != 0;
}
} // namespace aimassist
