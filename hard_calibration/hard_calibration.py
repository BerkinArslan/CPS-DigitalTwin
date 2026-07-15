import numpy as np
from sklearn.linear_model import LinearRegression
from collections import deque

# ── Triggers that require hard calibration ────────────────────────────────
# When any of these strings are passed to on_status_event(), the buffer is
# wiped and the calibration gate is re-armed.
#
# These are real status strings published on the bus — nothing is manual.
#
# From P01 (soil moisture sensor) via pipeline on_bad_status callback:
#   "sensor_disconnected" — sensor unplugged or replaced
#   "sensor_error"        — hardware fault on the sensor
#
# From P08 (anomaly detection) via pipeline on_anomaly_event callback:
#   "sensor_fault"        — P08 flagged implausible or stuck P01 readings
#   "system_fault"        — P01 node went silent / missed heartbeat
#   "process_fault"       — physical process anomaly (e.g. no moisture change after watering)
HARD_CALIBRATION_TRIGGERS = {
    "sensor_disconnected",
    "sensor_error",
    "sensor_fault",
    "system_fault",
    "process_fault",
}


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


    def add_sample(self, timestamp: float, SM: float, ET_0: float):
        """
        Called every time a new soil moisture sample arrives from the soil moisture team (P01).
        ET_0 comes from OpenMeteo for the same timestamp.
        Data is always collected into the buffer.
        Calibration only runs if a status event has armed the gate.
        Returns K_mc if calibration ran this call, otherwise returns None.
        """
        self.buffer.append({"timestamp": timestamp, "Soil_moisture": SM, "ET_0": ET_0})

        # Only calibrate if an event has triggered it AND buffer is full
        if self.calibration_needed and len(self.buffer) == self.batch_size:
            self.least_square_fit()
            self.calibration_needed = False  # disarm — wait for next event
            return self.K_mc


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
            y = SM_t - SM_{t+1}          (actual soil moisture drop between consecutive readings)
            x = K_c * ET_0 * delta_t     (model's expected SM drop without K_mc)
        No intercept — physics requires the line to pass through the origin.
        Returns K_mc as float.
        """
        timestamps  = np.array([s["timestamp"] for s in self.buffer])
        SM_values   = np.array([s["Soil_moisture"]        for s in self.buffer])
        ET_0_values = np.array([s["ET_0"]      for s in self.buffer])

        delta_t = np.diff(timestamps)                    # time between consecutive readings
        y = SM_values[:-1] - SM_values[1:]              # actual SM drop per consecutive pair
        x = self.K_c * ET_0_values[:-1] * delta_t      # expected SM drop per pair without K_mc

        model = LinearRegression(fit_intercept=False)
        model.fit(x.reshape(-1, 1), y)
        self.K_mc = model.coef_[0]

        return self.K_mc
