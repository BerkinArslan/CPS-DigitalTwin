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
    Soft calibration of the WATR microclimate correction coefficient (m).

    ET_crop = m × K_c × ET_0

    Soft calibration fits m against the RATE OF CHANGE of soil moisture (Δq),
    not absolute moisture levels.  This makes it immune to additive sensor drift:
    """
    def __init__(self, sensor_id, batch_size = 10, stable_needed=3, tolerance = 0.005, max_update = 50 ):
        self.sensor_id = sensor_id
        self.batch_size = batch_size
        self.stable_needed = stable_needed
        self.tolerance = tolerance
        self.max_update = max_update
        """
        sensor_id    : a name or ID for this sensor (used in log messages)
        batch_size   : how many samples to collect before each m update
        max_updates  : stop updating after this many batches
        tolerance    : |m_new - m_prev| must be smaller than this to count as "stable"
        stable_needed: how many consecutive stable updates = converged
        """
        self.m = 1.0  # initial guess for m
        self.m_history = []  # history of m values for logging
        self.stable_count = 0  # how many consecutive stable updates have we seen?
        self.update_count = 0  # how many updates have we done so far?
        self.converged = False  # has the calibration converged?

        self.sensor_drops  = []  # list to hold the last batch of Δq values
        self.predicted_drops = []  # list to hold the last batch of predicted Δq values

    
    def add_sample(self, q_sensor_previous, q_sensor_current, q_predicted_previous, q_predicted_current):
        """
        Add a new sample of Δq values to the batch.  When the batch is full,
        perform a calibration update.
        """
        difference_sensor = q_sensor_current - q_sensor_previous
        self.sensor_drops.append(difference_sensor)

        difference_predicted = q_predicted_current - q_predicted_previous
        self.predicted_drops.append(difference_predicted)

    def batch_ready(self):
        """
        Check if we have enough samples to perform a calibration update.
        """
        return len(self.sensor_drops) >= self.batch_size 
        
        
    def update_m(self):
        """
        Perform a calibration update using the current batch of Δq values.
        """
        
        sensor_drops = self.sensor_drops[:self.batch_size]
        predicted_drops = self.predicted_drops[:self.batch_size]

        expected_drops = [drop/self.m for drop in predicted_drops]

        numerator= sum(pred*exp for pred, exp in zip(sensor_drops, expected_drops))
        denominator = sum(exp**2 for exp in expected_drops)

        m_new = numerator / denominator

        self._check_convergence(m_new)

        self.m = m_new
        self.m_history.append(m_new)
        self.update_count +=1

        # discard used samples; keep any overflow for the next batch
        self.sensor_drops = self.sensor_drops[self.batch_size:]
        self.predicted_drops = self.predicted_drops[self.batch_size:]

        return m_new


    def _check_convergence(self, m_new):
        """
        Like a win streak in sport: count consecutive stable updates.
        One unstable update resets the streak to zero.
        """
        if len(self.m_history) == 0:
            
            return #nothing to compare to yet
        
        change = abs(m_new - self.m_history[-1])

        if change < self.tolerance:
            self.stable_count += 1
        else:
            self.stable_count = 0 # streak broken, hard reset

        if self.stable_count >= self.stable_needed:
            self.converged = True
            print(f"Calibration converged after {self.update_count} updates. Final m: {m_new:.4f}")

    def apply(self, kc, et0):
        """
        Apply the current m to compute ET_crop prediction to get the calibrated crop evapotranspiration.
        """
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
 

        