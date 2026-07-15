"""
soft_calibration.py
====================
Soft calibration of the microclimate correction factor m.

    ET_crop = m × K_c × ET_0

m corrects for your balcony microclimate vs open-field conditions.
Soft Cal finds m by comparing how much moisture the sensor measured
dropping versus how much the model expected to drop:

    m = measured_drop / (K_c × ET_0)

We work with daily drops (differences) instead of absolute readings
so that any constant sensor offset cancels out automatically.
"""

import json
import os


class SoftCalibrator:
    """
    Finds and tracks m — the balcony microclimate correction factor.

    Usage:
        cal = SoftCalibrator(sensor_id="P01")

        cal.add_sample(moisture_prev=45.0, moisture_curr=43.0,
                       predicted_prev=45.8, predicted_curr=43.4)

        if cal.batch_ready():
            cal.update_m()

        print(cal.m)
    """

    def __init__(self,
                 sensor_id,
                 batch_size=10,
                 max_updates=50,
                 convergence_tolerance=0.005,
                 stable_streak_needed=3):
        """
        sensor_id             : name for this sensor, used in log messages
        batch_size            : samples to collect before each m update
        max_updates           : hard stop after this many updates
        convergence_tolerance : |m_new - m_prev| must be below this to count as stable
        stable_streak_needed  : how many stable updates in a row = converged
        """

        self.sensor_id             = sensor_id
        self.batch_size            = batch_size
        self.max_updates           = max_updates
        self.convergence_tolerance = convergence_tolerance
        self.stable_streak_needed  = stable_streak_needed

        self.m             = 1.0   # start with no correction (m = 1 means balcony = open field)
        self.m_history     = []    # m value after each batch update
        self.stable_streak = 0     # how many stable updates in a row so far
        self.update_count  = 0     # total batch updates done
        self.converged     = False

        # Buffers filled by add_sample(), consumed by update_m()
        self.sensor_drops    = []  # how much moisture the sensor measured dropping each step
        self.predicted_drops = []  # how much the model predicted dropping each step


    # -------------------------------------------------------------------------
    # Step 1 — Feed one time step of data into the buffer
    # -------------------------------------------------------------------------

    def add_sample(self, moisture_prev, moisture_curr,
                   predicted_prev, predicted_curr):
        """
        Call this every time step with live sensor and model values.

        moisture_prev   : sensor reading at the previous time step
        moisture_curr   : sensor reading now
        predicted_prev  : model predicted moisture at the previous time step
        predicted_curr  : model predicted moisture now
        """
        sensor_drop    = moisture_curr  - moisture_prev    # negative = moisture fell
        predicted_drop = predicted_curr - predicted_prev

        self.sensor_drops.append(sensor_drop)
        self.predicted_drops.append(predicted_drop)


    # -------------------------------------------------------------------------
    # Step 2 — Check if we have enough samples to run an update
    # -------------------------------------------------------------------------

    def batch_ready(self):
        """Returns True when the buffer has batch_size or more samples."""
        return len(self.sensor_drops) >= self.batch_size


    # -------------------------------------------------------------------------
    # Step 3 — Compute a new m from the current batch
    # -------------------------------------------------------------------------

    def update_m(self):
        """
        Computes a new m from the collected batch and returns it.

        Core idea:
            sensor_drop  =  m  ×  expected_drop
            so m  =  Σ(sensor_drop × expected_drop) / Σ(expected_drop²)

        expected_drop is the drop the model predicts when m = 1
        (i.e. just K_c × ET_0, no balcony correction).
        We get it by dividing predicted_drop by our current m guess.
        """

        if self.converged or self.update_count >= self.max_updates:
            print(f"[{self.sensor_id}] Skipping — already done.")
            return self.m

        sensor_drops    = self.sensor_drops[:self.batch_size]
        predicted_drops = self.predicted_drops[:self.batch_size]

        # predicted_drop already has m baked in: predicted_drop = m_current × K_c × ET_0
        # divide by m_current to strip m out → leaves just K_c × ET_0
        expected_drops = [drop / self.m for drop in predicted_drops]

        numerator   = sum(s * e for s, e in zip(sensor_drops, expected_drops))
        denominator = sum(e * e for e in expected_drops)

        if denominator == 0:
            print(f"[{self.sensor_id}] Warning: all expected drops are zero — skipping batch.")
            self.sensor_drops    = self.sensor_drops[self.batch_size:]
            self.predicted_drops = self.predicted_drops[self.batch_size:]
            return self.m

        m_new = numerator / denominator

        self._check_convergence(m_new)

        self.m = m_new
        self.m_history.append(m_new)
        self.update_count += 1

        # discard used samples; keep any overflow for the next batch
        self.sensor_drops    = self.sensor_drops[self.batch_size:]
        self.predicted_drops = self.predicted_drops[self.batch_size:]

        print(f"[{self.sensor_id}] m = {m_new:.4f}  "
              f"(batch {self.update_count}/{self.max_updates})")

        return m_new


    # -------------------------------------------------------------------------
    # Step 4 — Streak counter: did m stop changing?
    # -------------------------------------------------------------------------

    def _check_convergence(self, m_new):
        """
        Like a win streak in sport: count consecutive stable updates.
        One unstable update resets the streak to zero.
        """
        if len(self.m_history) == 0:
            return  # nothing to compare against yet

        change = abs(m_new - self.m_history[-1])

        if change < self.convergence_tolerance:
            self.stable_streak += 1
        else:
            self.stable_streak = 0  # streak broken — hard reset

        if self.stable_streak >= self.stable_streak_needed:
            self.converged = True
            print(f"[{self.sensor_id}] *** Converged at m = {m_new:.4f} ***")


    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def apply(self, kc, et0):
        """Returns ET_crop = m × K_c × ET_0 using the current m."""
        return self.m * kc * et0


    def status(self):
        """Current calibration state as a plain dictionary."""
        return {
            "sensor_id":     self.sensor_id,
            "m":             round(self.m, 5),
            "updates_done":  self.update_count,
            "max_updates":   self.max_updates,
            "converged":     self.converged,
            "stable_streak": self.stable_streak,
            "buffer_size":   len(self.sensor_drops),
        }


    def save(self, path):
        """Save current state to a JSON file so calibration can resume later."""
        state = {
            "sensor_id":             self.sensor_id,
            "m":                     self.m,
            "m_history":             self.m_history,
            "update_count":          self.update_count,
            "stable_streak":         self.stable_streak,
            "converged":             self.converged,
            "batch_size":            self.batch_size,
            "max_updates":           self.max_updates,
            "convergence_tolerance": self.convergence_tolerance,
            "stable_streak_needed":  self.stable_streak_needed,
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[{self.sensor_id}] Saved to {path}")


    def load(self, path):
        """Load state from a JSON file. Returns True if the file existed."""
        if not os.path.exists(path):
            return False
        with open(path, "r") as f:
            state = json.load(f)

        self.m                     = state["m"]
        self.m_history             = state["m_history"]
        self.update_count          = state["update_count"]
        self.stable_streak         = state["stable_streak"]
        self.converged             = state["converged"]
        self.batch_size            = state["batch_size"]
        self.max_updates           = state["max_updates"]
        self.convergence_tolerance = state["convergence_tolerance"]
        self.stable_streak_needed  = state["stable_streak_needed"]

        print(f"[{self.sensor_id}] Loaded — m = {self.m:.4f}, "
              f"{self.update_count} batches already done.")
        return True


# =============================================================================
# Smoke test — run this file directly to verify it works
# =============================================================================

if __name__ == "__main__":

    import random
    random.seed(42)

    cal = SoftCalibrator(sensor_id="P01", batch_size=5, max_updates=20,
                         convergence_tolerance=0.005, stable_streak_needed=3)

    TRUE_M = 0.85
    OFFSET = 5.0   # constant sensor offset — result should be unaffected

    print(f"Starting m = {cal.m}   |   True m = {TRUE_M}   |   Sensor offset = +{OFFSET}")
    print("-" * 60)

    moisture_true = 60.0
    moisture_pred = 60.0

    for step in range(100):
        daily_true_drop = random.uniform(0.2, 0.8) * TRUE_M

        moisture_true_prev = moisture_true
        moisture_true     -= daily_true_drop

        moisture_sensor_prev = moisture_true_prev + OFFSET
        moisture_sensor_curr = moisture_true      + OFFSET

        daily_model_drop   = daily_true_drop / TRUE_M * cal.m
        moisture_pred_prev = moisture_pred
        moisture_pred     -= daily_model_drop

        cal.add_sample(moisture_prev=moisture_sensor_prev,
                       moisture_curr=moisture_sensor_curr,
                       predicted_prev=moisture_pred_prev,
                       predicted_curr=moisture_pred)

        if cal.batch_ready():
            cal.update_m()

        if cal.converged:
            print(f"\nConverged at step {step}!")
            break

    print()
    print("Final status:", cal.status())
    print(f"\nExpected m ≈ {TRUE_M},  got m = {cal.m:.4f}")
