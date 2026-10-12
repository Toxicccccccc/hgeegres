// Tests for input binding resolution.
//
// The GUI keybind control stores an integer virtual-key code, which the native
// config bridge writes as a decimal string. If that binding fails to resolve the
// engine polls "no key" and the lock does nothing even while the button is held.
// These checks pin the resolution rules so that regression cannot return.
#include "aimassist/input.hpp"

#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
void require(bool condition, char const* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}
} // namespace

int main()
{
    try
    {
        // --- binding resolution -------------------------------------------------
        // Numeric codes are what the GUI's keybind control stores and what the
        // native config bridge writes ("2" for right mouse, "5" for X1, ...).
        require(aimassist::resolve_input_key("2") == 2, "numeric VK '2' must resolve");
        require(aimassist::resolve_input_key("5") == 5, "numeric VK '5' must resolve");
        require(aimassist::resolve_input_key("1") == 1, "numeric VK '1' must resolve");
        // Spelled names, in both the engine's and the schema's spellings.
        require(aimassist::resolve_input_key("Left mouse") == 1, "'Left mouse' resolves");
        require(aimassist::resolve_input_key("Left Mouse") == 1, "'Left Mouse' resolves");
        require(aimassist::resolve_input_key("Right mouse") == 2, "'Right mouse' resolves");
        require(aimassist::resolve_input_key("Mouse 4 (X1)") == 5, "'Mouse 4 (X1)' resolves");
        require(aimassist::resolve_input_key("Alt") == 18, "'Alt' resolves");
        require(aimassist::resolve_input_key("caps lock") == 20, "'caps lock' resolves");
        // Unknown/missing bindings must not resolve to a real key silently.
        require(aimassist::resolve_input_key("garbage") == 0, "unknown name -> no key");
        require(aimassist::resolve_input_key("") == 0, "empty binding -> no key");

        std::cout << "input tests passed\n";
        return 0;
    }
    catch (std::exception const& error)
    {
        std::cerr << "input tests failed: " << error.what() << '\n';
        return 1;
    }
}
