"""SigmaDrift: biomechanically-grounded mouse movement generation.

This is the Python counterpart of ``native/include/aimassist/sigma_drift.hpp``,
so the Ultralytics (``.pt`` / ``.onnx``) engine and the native TensorRT
(``.engine``) engine produce the same trajectory style. It replaces the old
per-frame "distance gain / smoothness" correction, which is the heuristic that
statistical analysis flags: no Fitts' Law timing, a jagged velocity profile, and
a sub-movement count far above what a human produces.

The model composes six components from the motor-control literature:

* Sigma-lognormal velocity primitives (Plamondon's Kinematic Theory): progress
  along each stroke is the analytic lognormal CDF, so the velocity profile is
  bell-shaped with no numerical integration.
* Surge architecture (Costello 2017): one ballistic stroke that reaches 92-97%
  of the distance (15% of the time it overshoots 102-108%), then up to two
  small corrective sub-movements.
* Ornstein-Uhlenbeck lateral drift: a mean-reverting hand wander, integrated
  with the Euler-Maruyama scheme.
* Signal-dependent noise (Harris & Wolpert 1998): motor noise scales with the
  magnitude of the motor command, so fast strokes are noisier.
* Physiological tremor: an 8-12 Hz band, suppressed while the hand moves fast
  (proprioceptive damping) and fully expressed during slow correction.
* Gamma-distributed sampling intervals, matching real mouse polling irregularity.

The generator is O(1) per step and allocation-light, so it is safe in the live
inference loop.
"""

import math
import random

__all__ = ["SigmaDriftConfig", "SigmaDrift"]


class SigmaDriftConfig:
    """Tunable parameters. Defaults match the reference implementation."""

    __slots__ = (
        "fitts_a",
        "fitts_b",
        "target_width",
        "undershoot_min",
        "undershoot_max",
        "peak_time_ratio",
        "primary_sigma_min",
        "primary_sigma_max",
        "overshoot_prob",
        "overshoot_min",
        "overshoot_max",
        "correction_sigma_min",
        "correction_sigma_max",
        "second_correction_prob",
        "curvature_scale",
        "ou_theta",
        "ou_sigma",
        "tremor_freq_min",
        "tremor_freq_max",
        "tremor_amp_min",
        "tremor_amp_max",
        "sdn_k",
        "sample_dt_mean",
        "snap",
    )

    def __init__(self):
        # Fitts' Law constants (Shannon formulation). Calibrate per game.
        self.fitts_a = 50.0
        self.fitts_b = 150.0
        # Expected target width in pixels; smaller targets move more carefully.
        self.target_width = 20.0

        self.undershoot_min = 0.92
        self.undershoot_max = 0.97
        self.peak_time_ratio = 0.35
        self.primary_sigma_min = 0.18
        self.primary_sigma_max = 0.28

        self.overshoot_prob = 0.15
        self.overshoot_min = 1.02
        self.overshoot_max = 1.08
        self.correction_sigma_min = 0.12
        self.correction_sigma_max = 0.20
        self.second_correction_prob = 0.25

        self.curvature_scale = 0.025

        self.ou_theta = 3.5
        self.ou_sigma = 1.2

        self.tremor_freq_min = 8.0
        self.tremor_freq_max = 12.0
        self.tremor_amp_min = 0.15
        self.tremor_amp_max = 0.55

        self.sdn_k = 0.04

        self.sample_dt_mean = 7.8

        # Snap: 0-1, how directly the stroke reaches the target. The biomechanical
        # defaults model a deliberate human reach and are far too slow and noisy
        # for aim assist; snap scales the movement time and the add-on noise so a
        # lock closes fast and lands cleanly. 0 keeps the full human model.
        self.snap = 0.8


def _normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _lognormal_cdf(t, t0, mu, sigma):
    if t <= t0:
        return 0.0
    return _normal_cdf((math.log(t - t0) - mu) / sigma)


def _lognormal_pdf(t, t0, mu, sigma):
    if t <= t0:
        return 0.0
    dt = t - t0
    z = (math.log(dt) - mu) / sigma
    return 1.0 / (sigma * math.sqrt(2.0 * math.pi) * dt) * math.exp(-0.5 * z * z)


def _curvature_profile(s):
    # s^2*(1-s)^3 normalised to peak at s=0.4: curvature peaks during the
    # acceleration phase, not the midpoint, matching real trajectories.
    if s <= 0.0 or s >= 1.0:
        return 0.0
    value = s * s * (1.0 - s) * (1.0 - s) * (1.0 - s)
    norm = 0.4 * 0.4 * 0.6 * 0.6 * 0.6
    return value / norm


def _direction_factor(angle):
    # Vertical movements curve more than horizontal ones (wrist vs forearm).
    sa = abs(math.sin(angle))
    ca = abs(math.cos(angle))
    return 0.5 + 0.8 * sa - 0.15 * ca


def _correction_at(correction, t):
    """Progress (0-1) and instantaneous speed of one correction at time ``t``.

    Keeps the CDF and PDF of a correction sub-movement evaluated from the same
    parameters in a single place.
    """
    t0, mu, sigma = correction["t0"], correction["mu"], correction["sigma"]
    progress = _lognormal_cdf(t, t0, mu, sigma)
    speed = _lognormal_pdf(t, t0, mu, sigma)
    return progress, speed


class SigmaDrift:
    """Forward-generative pointing model, one movement at a time.

    Call :meth:`begin_move` when a new target is acquired, then :meth:`step`
    each frame. ``step`` returns the integer delta for that frame and reports
    ``active`` False once the movement has converged.
    """

    def __init__(self, config=None):
        self.config = config or SigmaDriftConfig()
        self._rng = random.Random()
        self._active = False
        self._corrections = []
        self._emitted_x = 0
        self._emitted_y = 0
        self._t = 0.0
        self._last_t = 0.0
        self._ou_x = 0.0
        self._ou_y = 0.0

    @property
    def active(self):
        return self._active

    def stop(self):
        self._active = False

    def begin_move(self, start_x, start_y, target_x, target_y):
        """Plan a new movement from the current aim to the target."""
        cfg = self.config
        self._start_x = float(start_x)
        self._start_y = float(start_y)
        self._target_x = float(target_x)
        self._target_y = float(target_y)
        self._t = 0.0
        self._last_t = 0.0
        self._ou_x = self._ou_y = 0.0
        # Reset the emitted-progress bookkeeping: step() reports the absolute
        # position of the plan relative to its origin, so a fresh movement must
        # start from zero or the aim stalls/snaps on the second acquisition.
        self._emitted_x = 0
        self._emitted_y = 0
        self._active = True

        dx = self._target_x - self._start_x
        dy = self._target_y - self._start_y
        distance = math.hypot(dx, dy)
        self._distance = distance
        if distance < 1.0:
            self._active = False
            return
        self._tx = dx / distance
        self._ty = dy / distance
        self._nx = -self._ty
        self._ny = self._tx

        snap = max(0.0, min(1.0, cfg.snap))
        movement_time = self._plan_primary_stroke(distance, snap)
        movement_time = self._plan_corrections(distance, movement_time, snap)
        self._plan_noise(distance, dy, dx, snap)
        self._plan_duration = movement_time * 1.15

    def _plan_primary_stroke(self, distance, snap):
        """Fitts'-Law movement time plus the primary lognormal stroke.

        Returns the movement time, which the correction and noise planners need
        to place their own components on the same timeline.
        """
        cfg = self.config
        rng = self._rng
        index_of_difficulty = math.log2(distance / cfg.target_width + 1.0)
        movement_time = (cfg.fitts_a + cfg.fitts_b * index_of_difficulty) * math.exp(
            rng.gauss(0.0, 0.08)
        )
        movement_time = max(movement_time, 80.0)
        # Snap compresses the movement time and the biomechanical add-on noise so
        # an aim-assist lock closes in a few frames instead of hundreds of ms.
        movement_time = max(movement_time * (1.0 - 0.875 * snap), 28.0)
        self._movement_time = movement_time

        overshoot = rng.random() < cfg.overshoot_prob * (1.0 - snap)
        if overshoot:
            reach = rng.uniform(cfg.overshoot_min, cfg.overshoot_max)
        else:
            reach = rng.uniform(cfg.undershoot_min, cfg.undershoot_max)
        # The human model undershoots and closes the gap with slow corrections;
        # snap pulls the primary reach toward the full distance so the aim does
        # not crawl onto the target for tens of frames.
        reach = reach + (1.0 - reach) * snap
        self._primary_distance = distance * reach

        primary_sigma = rng.uniform(cfg.primary_sigma_min, cfg.primary_sigma_max)
        primary_sigma *= 1.0 - 0.45 * snap
        self._primary_sigma = primary_sigma
        peak_ratio = max(0.10, cfg.peak_time_ratio - 0.22 * snap)
        peak_t = movement_time * rng.uniform(peak_ratio - 0.03, peak_ratio + 0.03)
        self._primary_mu = math.log(peak_t) + primary_sigma * primary_sigma
        return movement_time

    def _plan_corrections(self, distance, movement_time, snap):
        """One or two small corrective sub-movements closing the remaining gap."""
        cfg = self.config
        rng = self._rng
        self._corrections = []
        remaining = distance - self._primary_distance
        if abs(remaining) > 0.5:
            direction = 1.0 if remaining > 0.0 else -1.0
            c_d = abs(remaining) * rng.uniform(0.88, 1.02)
            c_sigma = rng.uniform(cfg.correction_sigma_min, cfg.correction_sigma_max)
            c_peak = movement_time * rng.uniform(0.12, 0.18)
            self._corrections.append(
                {
                    "distance": c_d,
                    "dir_x": self._tx * direction,
                    "dir_y": self._ty * direction,
                    "t0": movement_time * rng.uniform(0.55, 0.68),
                    "mu": math.log(c_peak) + c_sigma * c_sigma,
                    "sigma": c_sigma,
                }
            )
            left = remaining - c_d * direction
            if abs(left) > 0.3 and rng.random() < cfg.second_correction_prob:
                d2 = 1.0 if left > 0.0 else -1.0
                c_d2 = abs(left) * rng.uniform(0.85, 1.05)
                c_s2 = rng.uniform(0.10, 0.16)
                c_p2 = movement_time * rng.uniform(0.08, 0.12)
                self._corrections.append(
                    {
                        "distance": c_d2,
                        "dir_x": self._tx * d2,
                        "dir_y": self._ty * d2,
                        "t0": movement_time * rng.uniform(0.78, 0.88),
                        "mu": math.log(c_p2) + c_s2 * c_s2,
                        "sigma": c_s2,
                    }
                )
        return movement_time

    def _plan_noise(self, distance, dy, dx, snap):
        """Curvature, tremor and drift parameters, all damped by snap."""
        cfg = self.config
        rng = self._rng
        self._curvature_amplitude = (
            distance
            * cfg.curvature_scale
            * _direction_factor(math.atan2(dy, dx))
            * rng.gauss(0.0, 1.0)
            * (1.0 - 0.85 * snap)
        )
        noise_scale = 1.0 - 0.9 * snap
        self._tremor_frequency = rng.uniform(cfg.tremor_freq_min, cfg.tremor_freq_max)
        self._tremor_amplitude = rng.uniform(cfg.tremor_amp_min, cfg.tremor_amp_max) * noise_scale
        self._tremor_phase_x = rng.uniform(0.0, 2.0 * math.pi)
        self._tremor_phase_y = rng.uniform(0.0, 2.0 * math.pi)

    def _sample_at(self, t):
        cfg = self.config
        rng = self._rng
        dt_ms = max(t - self._last_t, 1.0) if self._last_t > 0.0 else cfg.sample_dt_mean
        self._last_t = t
        dt_s = dt_ms / 1000.0

        s = _lognormal_cdf(t, 0.0, self._primary_mu, self._primary_sigma)
        x = self._tx * self._primary_distance * s
        y = self._ty * self._primary_distance * s

        curve = self._curvature_amplitude * _curvature_profile(s)
        x += self._nx * curve
        y += self._ny * curve

        speed = self._primary_distance * _lognormal_pdf(
            t, 0.0, self._primary_mu, self._primary_sigma
        )
        for correction in self._corrections:
            cs, c_speed = _correction_at(correction, t)
            # Each correction travels along its own direction vector so an offset
            # correction does not smear diagonally.
            x += correction["dir_x"] * cs
            y += correction["dir_y"] * cs
            speed += c_speed

        # Euler-Maruyama step of the Ornstein-Uhlenbeck drift. The drift scales
        # down with snap so a fast lock does not wander off the target.
        snap = max(0.0, min(1.0, cfg.snap))
        drift_scale = 1.0 - 0.9 * snap
        self._ou_x += -cfg.ou_theta * self._ou_x * dt_s + cfg.ou_sigma * drift_scale * math.sqrt(dt_s) * rng.gauss(0.0, 1.0)
        self._ou_y += -cfg.ou_theta * self._ou_y * dt_s + cfg.ou_sigma * drift_scale * math.sqrt(dt_s) * rng.gauss(0.0, 1.0)

        # Tremor is suppressed while the hand moves fast (proprioceptive damping)
        # and fully expressed during slow correction.
        tremor_gain = 1.0 / (1.0 + speed * 0.3)
        t_s = t / 1000.0
        x += self._tremor_amplitude * tremor_gain * math.sin(
            2.0 * math.pi * self._tremor_frequency * t_s + self._tremor_phase_x
        )
        y += self._tremor_amplitude * tremor_gain * math.sin(
            2.0 * math.pi * self._tremor_frequency * t_s + self._tremor_phase_y
        )

        # Signal-dependent noise: motor noise scales with command magnitude,
        # damped by snap so a fast stroke lands cleanly on the target.
        sdn_scale = cfg.sdn_k * (1.0 - 0.9 * snap)
        x += sdn_scale * speed * rng.gauss(0.0, 1.0)
        y += sdn_scale * speed * rng.gauss(0.0, 1.0)

        return x + self._ou_x, y + self._ou_y

    def step(self, elapsed_ms, remainder_x=0.0, remainder_y=0.0):
        """Advance one frame.

        Returns ``(move_x, move_y, remainder_x, remainder_y, active)`` where the
        movement is the integer delta for this frame and the remainders carry the
        sub-pixel error so slow corrections are not lost to truncation.
        """
        if not self._active:
            return 0, 0, remainder_x, remainder_y, False
        self._t += max(elapsed_ms, 0.0)
        sample_x, sample_y = self._sample_at(self._t)
        raw_x = sample_x - self._emitted_x
        raw_y = sample_y - self._emitted_y
        move_x = int(raw_x + remainder_x)
        move_y = int(raw_y + remainder_y)
        remainder_x = raw_x + remainder_x - move_x
        remainder_y = raw_y + remainder_y - move_y
        self._emitted_x += move_x
        self._emitted_y += move_y

        dx = self._target_x - self._emitted_x
        dy = self._target_y - self._emitted_y
        if math.hypot(dx, dy) < 1.0 or self._t > self._plan_duration * 1.5:
            self._active = False
        return move_x, move_y, remainder_x, remainder_y, self._active
