#pragma once

// Modular movement/click output.
//
// Target tracking and movement math are independent of how a step actually
// reaches the game. This interface isolates that boundary so a backend can be
// swapped without touching targeting, and so the whole pipeline can be tested
// without hardware.
//
// Backends use documented, user-space interfaces only. In particular the
// Arduino path drives a real USB HID device: the game sees ordinary mouse
// input from real hardware, which is the appropriate and supportable way for an
// assistive interface to attach. No backend injects into another process,
// installs a driver, spoofs a device identity, or conceals itself.
//
// When a provider reports failure the engine releases held buttons and stops
// sending movement, so a disconnected device cannot leave an input stuck.

#include <memory>
#include <string>

namespace aimassist
{
    enum class InputKind
    {
        // Arduino Leonardo + USB Host Shield, driven over a serial port. The
        // existing, hardware-backed path.
        ArduinoSerial,
        // Records intended movement without touching any device. Used by tests and
        // by anyone who wants to see what the engine would have done.
        Simulated,
    };

    char const *to_string(InputKind kind) noexcept;

    // Resolves a configuration string ("arduino", "simulated") to a provider.
    InputKind input_kind_from_string(std::string const &name, bool &recognized) noexcept;

    class IInputProvider
    {
    public:
        virtual ~IInputProvider() = default;

        virtual InputKind kind() const noexcept = 0;

        // Human-readable description of the active connection for the GUI.
        virtual std::string describe() const = 0;

        // Establish the connection. `target` is backend-specific: for the Arduino it
        // is the serial port (for example "COM7"). Returns false with a reason.
        virtual bool connect(std::string const &target, std::string &message) = 0;

        virtual bool connected() const noexcept = 0;

        // Emit one movement step, optionally with a click. Returns false when the
        // step could not be delivered, which the engine treats as a device failure.
        virtual bool send(int move_x, int move_y, bool click) = 0;

        // Release any held button state. Called on shutdown, on lock release, and on
        // any error, so a button can never stay pressed.
        virtual void release_buttons() = 0;

        // Total steps accepted, for telemetry.
        virtual unsigned long long steps_sent() const noexcept = 0;

        virtual void close() = 0;
    };

    // Creates a provider. The caller owns the returned pointer.
    std::unique_ptr<IInputProvider> create_input_provider(InputKind kind);
} // namespace aimassist
