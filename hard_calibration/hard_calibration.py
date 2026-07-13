import numpy as np
from sklearn.linear_model import LinearRegression
from collections import deque

# ── Triggers that require hard calibration ────────────────────────────────
# These status strings are published by NINFO topic, Group 08, or the web app.
# When any of these arrive, the buffer is wiped and calibration is armed.
HARD_CALIBRATION_TRIGGERS = {
    "new_sensor",
    "sensor_position_changed",
    "flower_pot_location_changed",
    "system_rebooted",
    "drift_resolved"        # sent by Group 08 after resolving a sensor drift event
} # Changes might be requred in this strategy TTD


class HardCalibration:

    def __init__(self, K_c: float, batch_size: int):
        """
        K_c         : crop coefficient — fixed per plant species, known at startup
        batch_size  : how many samples to collect before running calibration
        """
        self.K_c = K_c
        self.batch_size = batch_size
        self.K_mc = None               # None means not yet calibrated
        self.buffer = deque(maxlen=batch_size)  # circular buffer, auto-drops oldest
        self.calibration_needed = False  # gate — only opened by a status event


    def add_sample(self, timestamp: float, ET: float, ET_0: float):
        """
        Called every time a new ET sample arrives from your friend's mapping function.
        Data is always collected into the buffer.
        Calibration only runs if a status event has armed the gate.
        """
        self.buffer.append({"timestamp": timestamp, "ET": ET, "ET_0": ET_0})

        # Only calibrate if an event has triggered it AND buffer is full
        if self.calibration_needed and len(self.buffer) == self.batch_size:
            self.least_square_fit()
            self.calibration_needed = False  # disarm — wait for next event


    def on_status_event(self, status: str):
        """
        Called every time a status message arrives from NINFO, Group 08, or the web app.
        If the status is a hard calibration trigger:
            - buffer is wiped (pre-event data discarded)
            - gate is armed (calibration will run once buffer fills with post-event data)
        """
        if status in HARD_CALIBRATION_TRIGGERS:
            self.buffer.clear()          # discard all data collected before the event
            self.K_mc = None             # old K_mc is no longer valid
            self.calibration_needed = True  # arm the gate


    def least_square_fit(self):
        """
        Runs OLS regression on the current buffer to find K_mc.
        Formula: y = K_mc * x
            y = ET_t - ET_{t+1}          (actual ET drop between consecutive readings)
            x = K_c * ET_0 * delta_t     (model's expected ET drop without K_mc)
        No intercept — physics requires the line to pass through the origin.
        """
        timestamps  = np.array([s["timestamp"] for s in self.buffer])
        ET_values   = np.array([s["ET"]        for s in self.buffer])
        ET_0_values = np.array([s["ET_0"]      for s in self.buffer])

        delta_t = np.diff(timestamps)                    # time between consecutive readings
        y = ET_values[:-1] - ET_values[1:]              # actual ET drop per pair
        x = self.K_c * ET_0_values[:-1] * delta_t      # expected ET drop per pair

        model = LinearRegression(fit_intercept=False)
        model.fit(x.reshape(-1, 1), y)
        self.K_mc = model.coef_[0]

        return self.K_mc
