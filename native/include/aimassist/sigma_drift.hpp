#pragma once

// SigmaDrift: biomechanically-grounded mouse movement generation.
//
// Replaces the heuristic WindMouse-style correction with a forward-generative
// model of human pointing, built from published motor-control research:
//
//   * Sigma-lognormal velocity primitives (Plamondon's Kinematic Theory) --
//     progress along each stroke is the analytic CDF of a lognormal, so the
//     velocity profile is bell-shaped without numerical integration.
//   * Surge architecture (Costello 2017) -- one ballistic stroke that reaches
//     92-97% of the distance (15% of the time it overshoots 102-108%), then
//     up to two small corrective sub-movements.
//   * Ornstein-Uhlenbeck lateral drift -- a mean-reverting stochastic hand
//     wander, integrated with Euler-Maruyama.
//   * Signal-dependent noise (Harris & Wolpert 1998) -- motor noise scales with
//     the magnitude of the motor command, so fast strokes are noisier.
//   * Physiological tremor -- an 8-12 Hz band, suppressed while the hand moves
//     fast (proprioceptive damping), fully expressed during slow correction.
//   * Gamma-distributed sampling intervals -- matches real mouse polling
//     irregularity instead of a uniform tick.
//
// Unlike the accessibility shaper it replaces for trajectory generation, this
// produces the trajectory statistics that real human pointing exhibits, while
// remaining O(N) and allocation-light for the live loop.
//
// Usage from the engine loop: call begin_move() once when a new target is
// acquired (or the aim error grows again), then poll step() each frame. step()
// returns the incremental integer delta for this frame and false when the
// movement has converged, at which point the caller resumes direct correction.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

namespace aimassist
{
    struct SigmaDriftConfig
    {
        // Fitts' Law constants (Shannon formulation). Calibrate per game.
        double fitts_a{50.0};
        double fitts_b{150.0};
        // Expected target width in pixels; smaller targets move more carefully.
        double target_width{20.0};

        double undershoot_min{0.92};
        double undershoot_max{0.97};
        double peak_time_ratio{0.35};
        double primary_sigma_min{0.18};
        double primary_sigma_max{0.28};

        double overshoot_prob{0.15};
        double overshoot_min{1.02};
        double overshoot_max{1.08};
        double correction_sigma_min{0.12};
        double correction_sigma_max{0.20};
        double second_correction_prob{0.25};

        double curvature_scale{0.025};

        double ou_theta{3.5};
        double ou_sigma{1.2};

        double tremor_freq_min{8.0};
        double tremor_freq_max{12.0};
        double tremor_amp_min{0.15};
        double tremor_amp_max{0.55};

        double sdn_k{0.04};

        double sample_dt_mean{7.8};
        double gamma_shape{3.5};

        // Snap: 0-1, how directly the stroke reaches the target. The biomechanical
        // defaults (fitts_a/fitts_b, drift, tremor, SDN) model a deliberate human
        // reach and are far too slow and noisy for aim assist. Snap scales the
        // movement time down and the add-on noise with it, so 0 keeps the full
        // human model and 1 is a fast, clean lock. Applied per movement, so it is
        // safe to change between acquisitions.
        double snap{0.8};
        // Hard lock: skip the generative trajectory entirely and put the crosshair
        // on the target in a single step. This is the lowest-latency tracking mode
        // -- no stroke ramp, no drift, no tremor -- for players who want the aim
        // pinned to the target rather than following it a frame behind.
        bool direct{false};
    };

    class SigmaDrift
    {
    public:
        void set_config(SigmaDriftConfig const& config)
        {
            config_ = config;
        }

        SigmaDriftConfig const& config() const noexcept
        {
            return config_;
        }

        // Plan a new movement from the current aim to the target. Call once per
        // acquisition; every step() afterwards follows the plan.
        void begin_move(float start_x, float start_y, float target_x, float target_y)
        {
            start_x_ = start_x;
            start_y_ = start_y;
            target_x_ = target_x;
            target_y_ = target_y;
            t_ = 0.0;
            last_t_ = 0.0;
            active_ = true;
            ou_x_ = ou_y_ = 0.0;
            // Reset the emitted-progress bookkeeping: step() reports the absolute
            // position of the plan relative to its origin, so it must start from
            // zero for every new movement. Without this, a second movement would
            // emit deltas measured against the previous one and the aim would
            // stall or snap back.
            emitted_x_ = 0;
            emitted_y_ = 0;
            plan_stroke();
        }

        // True while a planned movement is in flight.
        bool active() const noexcept
        {
            return active_;
        }

        void stop()
        {
            active_ = false;
        }

        // Advance one frame: consumes real elapsed time and returns the integer
        // delta to send this frame. output_x/output_y receive the step.
        void step(double elapsed_ms, int& output_x, int& output_y)
        {
            output_x = 0;
            output_y = 0;
            if (!active_)
            {
                return;
            }
            // Direct (hard lock) mode: emit the full remaining correction at once
            // and finish. This is the minimum possible latency to the target.
            if (config_.direct)
            {
                output_x = static_cast<int>(target_x_) - emitted_x_;
                output_y = static_cast<int>(target_y_) - emitted_y_;
                emitted_x_ += output_x;
                emitted_y_ += output_y;
                active_ = false;
                return;
            }
            t_ += elapsed_ms;
            auto const sample = sample_at(t_);
            auto const x = static_cast<int>(sample.first - emitted_x_);
            auto const y = static_cast<int>(sample.second - emitted_y_);
            output_x = x;
            output_y = y;
            emitted_x_ += x;
            emitted_y_ += y;

            auto const dx = target_x_ - emitted_x_;
            auto const dy = target_y_ - emitted_y_;
            if (std::sqrt(dx * dx + dy * dy) < 1.0F
                || t_ > plan_duration_ms_ * 1.5)
            {
                active_ = false;
            }
        }

    private:
        static double normal_cdf(double x)
        {
            return 0.5 * (1.0 + std::erf(x / 1.4142135623730951));
        }

        static double lognormal_cdf(double t, double t0, double mu, double sigma)
        {
            if (t <= t0)
            {
                return 0.0;
            }
            return normal_cdf((std::log(t - t0) - mu) / sigma);
        }

        static double lognormal_pdf(double t, double t0, double mu, double sigma)
        {
            if (t <= t0)
            {
                return 0.0;
            }
            double const dt = t - t0;
            double const z = (std::log(dt) - mu) / sigma;
            return 1.0 / (sigma * 2.5066282746310002 * dt)
                * std::exp(-0.5 * z * z);
        }

        // s^2*(1-s)^3 normalised to peak at s=0.4: curvature peaks during the
        // acceleration phase, not the midpoint, matching real trajectories.
        static double curvature_profile(double s)
        {
            if (s <= 0.0 || s >= 1.0)
            {
                return 0.0;
            }
            double const v = s * s * (1.0 - s) * (1.0 - s) * (1.0 - s);
            constexpr double norm = 0.4 * 0.4 * 0.6 * 0.6 * 0.6;
            return v / norm;
        }

        // Vertical movements curve more than horizontal ones (wrist vs forearm).
        static double direction_factor(double angle)
        {
            double const sa = std::abs(std::sin(angle));
            double const ca = std::abs(std::cos(angle));
            return 0.5 + 0.8 * sa - 0.15 * ca;
        }

        void plan_stroke()
        {
            auto const dx = target_x_ - start_x_;
            auto const dy = target_y_ - start_y_;
            distance_ = std::sqrt(dx * dx + dy * dy);
            if (distance_ < 1.0)
            {
                active_ = false;
                return;
            }
            // Hard lock bypasses the generative model: the whole correction is
            // emitted on the first step and the movement ends. There is no ramp,
            // drift, tremor or motor noise to add lag or wobble.
            if (config_.direct)
            {
                tx_ = dx / distance_;
                ty_ = dy / distance_;
                nx_ = -ty_;
                ny_ = tx_;
                primary_distance_ = distance_;
                corrections_.clear();
                curvature_amplitude_ = 0.0;
                tremor_amplitude_ = 0.0;
                primary_sigma_ = config_.primary_sigma_min;
                primary_mu_ = std::log(std::max(distance_, 1.0));
                movement_time_ms_ = 0.0;
                plan_duration_ms_ = 0.0;
                return;
            }
            tx_ = dx / distance_;
            ty_ = dy / distance_;
            nx_ = -ty_;
            ny_ = tx_;

            auto const id = std::log2(distance_ / config_.target_width + 1.0);
            std::normal_distribution<double> jitter(0.0, 0.08);
            auto mt = (config_.fitts_a + config_.fitts_b * id)
                * std::exp(jitter(rng_));
            mt = std::max(mt, 80.0);
            // Snap compresses the movement time. The Fitts time is a deliberate
            // human reach (hundreds of ms); for aim assist the stroke must close
            // the gap in a few frames, so at snap=1 the time is cut by up to 8x
            // and the dead lead-in that made the first ~80ms emit nothing shrinks
            // with it. Also shrink the biomechanical add-ons proportionally, since
            // a fast lock that wanders is exactly the inaccuracy being fixed.
            auto const snap = std::clamp(config_.snap, 0.0, 1.0);
            auto const time_scale = 1.0 - 0.875 * snap;
            mt *= time_scale;
            mt = std::max(mt, 28.0);
            movement_time_ms_ = mt;
            // Noise scaling: full human noise at snap=0, nearly clean at snap=1.
            auto const noise_scale = 1.0 - 0.9 * snap;

            std::uniform_real_distribution<double> unit(0.0, 1.0);
            overshoot_ = unit(rng_) < config_.overshoot_prob * (1.0 - snap);
            double const reach = overshoot_
                ? unit(rng_) * (config_.overshoot_max - config_.overshoot_min) + config_.overshoot_min
                : unit(rng_) * (config_.undershoot_max - config_.undershoot_min) + config_.undershoot_min;
            // The human model deliberately undershoots (reach 0.92-0.97) and then
            // closes the last few pixels with slow corrective sub-movements. For
            // aim assist that leaves the crosshair crawling onto the target for
            // tens of frames, which is the inaccuracy being fixed, so snap pulls
            // the primary reach toward the full distance.
            auto const effective_reach = reach + (1.0 - reach) * snap;
            primary_distance_ = distance_ * effective_reach;

            primary_sigma_ = unit(rng_)
                * (config_.primary_sigma_max - config_.primary_sigma_min)
                + config_.primary_sigma_min;
            // A sharper sigma and an earlier peak kill the slow lead-in where the
            // lognormal CDF is still ~0, so the first frames after a lock already
            // move toward the target instead of emitting nothing.
            primary_sigma_ *= 1.0 - 0.45 * snap;
            double const peak_ratio = std::max(0.10, config_.peak_time_ratio - 0.22 * snap);
            double const peak_t = mt * (unit(rng_) * 0.06 + peak_ratio - 0.03);
            primary_mu_ = std::log(peak_t) + primary_sigma_ * primary_sigma_;

            corrections_.clear();
            double const remaining = distance_ - primary_distance_;
            if (std::abs(remaining) > 0.5)
            {
                double const dir = remaining > 0.0 ? 1.0 : -1.0;
                double const c_d = std::abs(remaining)
                    * (unit(rng_) * 0.14 + 0.88);
                double const c_sigma = unit(rng_)
                    * (config_.correction_sigma_max - config_.correction_sigma_min)
                    + config_.correction_sigma_min;
                double const c_peak = mt * (unit(rng_) * 0.06 + 0.12);
                corrections_.push_back({
                    c_d,
                    tx_ * dir,
                    ty_ * dir,
                    mt * (unit(rng_) * 0.13 + 0.55),
                    std::log(c_peak) + c_sigma * c_sigma,
                    c_sigma
                });
                double const left = remaining - c_d * dir;
                if (std::abs(left) > 0.3 && unit(rng_) < config_.second_correction_prob)
                {
                    double const d2 = left > 0.0 ? 1.0 : -1.0;
                    double const c_d2 = std::abs(left) * (unit(rng_) * 0.2 + 0.85);
                    double const c_s2 = unit(rng_) * 0.06 + 0.10;
                    double const c_p2 = mt * (unit(rng_) * 0.04 + 0.08);
                    corrections_.push_back({
                        c_d2,
                        tx_ * d2,
                        ty_ * d2,
                        mt * (unit(rng_) * 0.10 + 0.78),
                        std::log(c_p2) + c_s2 * c_s2,
                        c_s2
                    });
                }
            }

            curvature_amplitude_ = distance_ * config_.curvature_scale
                * direction_factor(std::atan2(dy, dx))
                * std::normal_distribution<double>(0.0, 1.0)(rng_)
                * (1.0 - 0.85 * snap);

            tremor_frequency_ = unit(rng_)
                * (config_.tremor_freq_max - config_.tremor_freq_min)
                + config_.tremor_freq_min;
            tremor_amplitude_ = (unit(rng_)
                * (config_.tremor_amp_max - config_.tremor_amp_min)
                + config_.tremor_amp_min) * noise_scale;
            tremor_phase_x_ = unit(rng_) * 6.283185307179586;
            tremor_phase_y_ = unit(rng_) * 6.283185307179586;

            plan_duration_ms_ = mt * 1.15;
        }

        // Position at time t (ms), including drift, tremor and motor noise.
        std::pair<double, double> sample_at(double t)
        {
            double const dt_ms = last_t_ > 0.0 ? std::max(t - last_t_, 1.0) : config_.sample_dt_mean;
            last_t_ = t;
            double const dt_s = dt_ms / 1000.0;

            double const s = lognormal_cdf(t, 0.0, primary_mu_, primary_sigma_);
            double x = tx_ * primary_distance_ * s;
            double y = ty_ * primary_distance_ * s;

            double const curve = curvature_amplitude_ * curvature_profile(s);
            x += nx_ * curve;
            y += ny_ * curve;

            double speed = primary_distance_
                * lognormal_pdf(t, 0.0, primary_mu_, primary_sigma_);
            for (auto const& correction : corrections_)
            {
                double const cs = lognormal_cdf(t, correction.t0, correction.mu, correction.sigma);
                // Each correction travels along its own direction vector, so an
                // offset correction does not smear diagonally (the old scalar
                // form added the same delta to both axes).
                x += correction.dir_x * correction.distance * cs;
                y += correction.dir_y * correction.distance * cs;
                speed += correction.distance
                    * lognormal_pdf(t, correction.t0, correction.mu, correction.sigma);
            }

            // Euler-Maruyama step of the Ornstein-Uhlenbeck drift. The drift
            // scales down with snap so a fast lock does not wander off the head.
            auto const drift_scale = 1.0 - 0.9 * std::clamp(config_.snap, 0.0, 1.0);
            ou_x_ += -config_.ou_theta * ou_x_ * dt_s
                + config_.ou_sigma * drift_scale * std::sqrt(dt_s)
                * std::normal_distribution<double>(0.0, 1.0)(rng_);
            ou_y_ += -config_.ou_theta * ou_y_ * dt_s
                + config_.ou_sigma * drift_scale * std::sqrt(dt_s)
                * std::normal_distribution<double>(0.0, 1.0)(rng_);

            // Tremor is suppressed while the hand moves fast (proprioceptive
            // damping) and fully expressed during slow correction.
            double const tremor_gain = 1.0 / (1.0 + speed * 0.3);
            double const t_s = t / 1000.0;
            x += tremor_amplitude_ * tremor_gain
                * std::sin(6.283185307179586 * tremor_frequency_ * t_s + tremor_phase_x_);
            y += tremor_amplitude_ * tremor_gain
                * std::sin(6.283185307179586 * tremor_frequency_ * t_s + tremor_phase_y_);

            // Signal-dependent noise: motor noise scales with command magnitude,
            // damped by snap so a fast stroke lands cleanly on the target.
            auto const sdn_scale = config_.sdn_k
                * (1.0 - 0.9 * std::clamp(config_.snap, 0.0, 1.0));
            x += sdn_scale * speed * std::normal_distribution<double>(0.0, 1.0)(rng_);
            y += sdn_scale * speed * std::normal_distribution<double>(0.0, 1.0)(rng_);

            return {x + ou_x_, y + ou_y_};
        }

        struct Correction
        {
            double distance{};
            double dir_x{};
            double dir_y{};
            double t0{};
            double mu{};
            double sigma{};
        };

        SigmaDriftConfig config_;
        std::mt19937 rng_{std::random_device{}()};

        float start_x_{}; float start_y_{};
        float target_x_{}; float target_y_{};
        double distance_{};
        double tx_{}; double ty_{}; double nx_{}; double ny_{};
        double movement_time_ms_{};
        double primary_distance_{};
        double primary_mu_{}; double primary_sigma_{};
        bool overshoot_{};
        double curvature_amplitude_{};
        double tremor_frequency_{}; double tremor_amplitude_{};
        double tremor_phase_x_{}; double tremor_phase_y_{};
        double plan_duration_ms_{};
        std::vector<Correction> corrections_;

        double t_{}; double last_t_{};
        double ou_x_{}; double ou_y_{};
        int emitted_x_{}; int emitted_y_{};
        bool active_{false};
    };
} // namespace aimassist
