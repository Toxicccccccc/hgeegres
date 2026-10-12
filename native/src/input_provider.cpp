#include "aimassist/input_provider.hpp"

#include "aimassist/serial_bridge.hpp"

#include <atomic>
#include <cstdint>
#include <mutex>
#include <vector>

namespace aimassist
{
    char const *to_string(InputKind kind) noexcept
    {
        switch (kind)
        {
        case InputKind::ArduinoSerial:
            return "arduino";
        case InputKind::Simulated:
            return "simulated";
        }
        return "unknown";
    }

    InputKind input_kind_from_string(std::string const &name, bool &recognized) noexcept
    {
        recognized = true;
        if (name == "simulated")
        {
            return InputKind::Simulated;
        }
        if (name == "arduino" || name.empty())
        {
            return InputKind::ArduinoSerial;
        }
        recognized = false;
        return InputKind::ArduinoSerial;
    }

    namespace
    {
        // Arduino Leonardo + USB Host Shield over the existing serial protocol.
        // The wire format is unchanged: "<x>,<y>,<click>*".
        class ArduinoInputProvider final : public IInputProvider
        {
        public:
            InputKind kind() const noexcept override
            {
                return InputKind::ArduinoSerial;
            }

            std::string describe() const override
            {
                if (!connected())
                {
                    return "Arduino: not connected";
                }
                return "Arduino HID bridge on " + bridge_.connected_port();
            }

            bool connect(std::string const &target, std::string &message) override
            {
                return bridge_.connect(target, message);
            }

            bool connected() const noexcept override
            {
                return !bridge_.connected_port().empty();
            }

            bool send(int move_x, int move_y, bool click) override
            {
                if (!bridge_.send_adjustment(move_x, move_y, click))
                {
                    return false;
                }
                steps_.fetch_add(1);
                return true;
            }

            void release_buttons() override
            {
                // The firmware clicks on demand rather than holding a button, so there
                // is no persistent pressed state to clear. Sending a zero move keeps a
                // pending click from being applied late.
                if (connected())
                {
                    bridge_.send_adjustment(0, 0, false);
                }
            }

            unsigned long long steps_sent() const noexcept override
            {
                return steps_.load();
            }

            void close() override
            {
                bridge_.close();
            }

        private:
            SerialBridge bridge_;
            std::atomic<unsigned long long> steps_{};
        };

        // Records intended movement without touching any device. This makes the entire
        // pipeline testable in automation and lets a user verify exactly what the
        // engine would send before connecting real hardware.
        class SimulatedInputProvider final : public IInputProvider
        {
        public:
            InputKind kind() const noexcept override
            {
                return InputKind::Simulated;
            }

            std::string describe() const override
            {
                return "Simulated output (no device is moved)";
            }

            bool connect(std::string const &target, std::string &message) override
            {
                (void)target;
                std::lock_guard<std::mutex> lock(mutex_);
                connected_ = true;
                history_.clear();
                message = "Simulated output active; movement is recorded but no device is moved";
                return true;
            }

            bool connected() const noexcept override
            {
                std::lock_guard<std::mutex> lock(mutex_);
                return connected_;
            }

            bool send(int move_x, int move_y, bool click) override
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (!connected_)
                {
                    return false;
                }
                steps_.fetch_add(1);
                if (click)
                {
                    clicks_.fetch_add(1);
                }
                // Keep a short tail so a test can assert the recent movement sequence
                // without unbounded memory growth during a long run.
                constexpr std::size_t max_history = 512;
                if (history_.size() >= max_history)
                {
                    history_.erase(history_.begin());
                }
                history_.push_back({move_x, move_y, click});
                return true;
            }

            void release_buttons() override
            {
                std::lock_guard<std::mutex> lock(mutex_);
                released_.fetch_add(1);
            }

            unsigned long long steps_sent() const noexcept override
            {
                return steps_.load();
            }

            void close() override
            {
                std::lock_guard<std::mutex> lock(mutex_);
                connected_ = false;
            }

            struct Step
            {
                int x{};
                int y{};
                bool click{};
            };

            std::vector<Step> recent_steps() const
            {
                std::lock_guard<std::mutex> lock(mutex_);
                return history_;
            }

            unsigned long long clicks() const noexcept
            {
                return clicks_.load();
            }

            unsigned long long releases() const noexcept
            {
                return released_.load();
            }

        private:
            mutable std::mutex mutex_;
            bool connected_{};
            std::vector<Step> history_;
            std::atomic<unsigned long long> steps_{};
            std::atomic<unsigned long long> clicks_{};
            std::atomic<unsigned long long> released_{};
        };
    } // namespace

    std::unique_ptr<IInputProvider> create_input_provider(InputKind kind)
    {
        switch (kind)
        {
        case InputKind::ArduinoSerial:
            return std::make_unique<ArduinoInputProvider>();
        case InputKind::Simulated:
            return std::make_unique<SimulatedInputProvider>();
        }
        return nullptr;
    }
} // namespace aimassist
