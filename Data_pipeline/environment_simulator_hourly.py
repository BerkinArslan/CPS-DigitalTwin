"""
Hourly (sped-up) environment simulator.

Drop-in replacement for environment_simulator.py: publishes to the SAME
MQTT topics with the SAME payload format, so the data pipeline and every
consumer work unchanged. Run this INSTEAD of environment_simulator.py
when demoing with a sped-up digital twin.

Difference: instead of republishing OpenMeteo's static "current" weather,
it fetches the HOURLY forecast once and walks through it at `time_scale`
(1 real second = time_scale simulated seconds). With time_scale=3600 the
published values sweep through a realistic day/night curve — irradiation
0 at night, smooth ramp to a midday peak — one simulated hour per real
second... published every `interval` seconds, so each publish advances
`interval` simulated hours.

Set time_scale to the SAME value you pass to auto_simulate() in
live_demo_sped_up.py so the twin's clock and the weather agree.

Usage:  python Data_pipeline/environment_simulator_hourly.py
"""

import time
import math
import random
import datetime
import requests

try:
    from Data_pipeline.environment_simulator import EnvironmentSimulator
except ImportError:  # when run directly from inside Data_pipeline/
    from environment_simulator import EnvironmentSimulator


class EnvironmentSimulatorHourly(EnvironmentSimulator):

    HOURLY_VARS = ("temperature_2m,relative_humidity_2m,surface_pressure,"
                   "wind_speed_10m,shortwave_radiation,soil_moisture_0_to_1cm")

    def __init__(self, broker: str, port: int, interval: int = 5,
                 time_scale: float = 900, forecast_days: int = 3,
                 bad_status_prob: float = 0.0):
        """
        :param interval: seconds between publish rounds (same as parent)
        :param time_scale: simulated seconds per real second (match the demo!)
        :param forecast_days: hours of forecast to fetch (max 16 days);
                              the profile wraps around for longer runs
        :param bad_status_prob: chance per publish of a bad sensor status.
               Default 0: a bad status makes the pipeline fall back to
               OpenMeteo's real *current* weather, which would rip the
               value out of the simulated day/night curve (e.g. jump from
               simulated night 0 W/m2 to real midday 500 W/m2). Set > 0
               only if you want to demo the fallback chain itself.
        """
        # set before super().__init__() because that calls _fetch_openmeteo()
        self.time_scale = time_scale
        self.forecast_days = forecast_days
        self.bad_status_prob = bad_status_prob
        self.interval = interval
        super().__init__(broker, port, interval)
        self.t0 = time.time()  # real start time of the simulated clock

    # ------------------------------------------------------------------
    # DATA SOURCE — one hourly-forecast fetch instead of "current" weather
    # ------------------------------------------------------------------

    def _fetch_openmeteo(self):
        print("[SimHourly] Fetching hourly forecast from OpenMeteo...")
        try:
            params = {
                "latitude":      self.OPENMETEO_LAT,
                "longitude":     self.OPENMETEO_LON,
                "hourly":        self.HOURLY_VARS,
                "forecast_days": self.forecast_days,
            }
            response = requests.get(self.OPENMETEO_URL, params=params, timeout=10)
            response.raise_for_status()
            self.hourly = response.json()["hourly"]

            # start the profile at the current real hour so day/night aligns
            current_hour = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
            try:
                self.start_idx = self.hourly["time"].index(current_hour)
            except ValueError:
                self.start_idx = 0

            print(f"[SimHourly] Got {len(self.hourly['time'])} forecast hours, "
                  f"starting at {self.hourly['time'][self.start_idx]} UTC.")

        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[SimHourly] OpenMeteo fetch failed: {e}. "
                  f"Using synthetic day/night cycle.")
            self._build_synthetic_day()

        self._apply_hour(0)  # sets the initial self.real_* values

    def _build_synthetic_day(self):
        """Offline fallback: one plausible 24 h profile, repeated forever."""
        hours = list(range(24))
        self.hourly = {
            "time": [f"synthetic {h:02d}:00" for h in hours],
            "temperature_2m":
                [round(16 + 7 * math.sin(math.pi * (h - 9) / 12), 1) for h in hours],
            "relative_humidity_2m":
                [round(65 - 15 * math.sin(math.pi * (h - 9) / 12), 1) for h in hours],
            "surface_pressure": [1013.0] * 24,
            "wind_speed_10m":
                [round(8 + 4 * math.sin(math.pi * (h - 12) / 12), 1) for h in hours],
            # 0 W/m2 at night, ~600 W/m2 midday peak between 6:00 and 18:00
            "shortwave_radiation":
                [round(max(0.0, 600 * math.sin(math.pi * (h - 6) / 12)), 1) for h in hours],
            "soil_moisture_0_to_1cm": [0.3] * 24,
        }
        self.start_idx = 0

    def _apply_hour(self, offset_hours: int):
        """Loads the forecast values for start hour + offset into the same
        self.real_* attributes the parent's publish methods read."""
        n = len(self.hourly["time"])
        idx = (self.start_idx + offset_hours) % n  # wrap for long runs

        def val(field, default):
            v = self.hourly.get(field, [None] * n)[idx]
            return default if v is None else v

        self.sim_time_label     = self.hourly["time"][idx]
        self.real_temperature   = val("temperature_2m", 18.0)
        self.real_humidity      = val("relative_humidity_2m", 60.0)
        self.real_pressure      = val("surface_pressure", 1013.0)
        self.real_wind_10m      = val("wind_speed_10m", 10.0)
        # W/m2, published as-is in the light_lux field — consistent with the
        # parent simulator and the pipeline fallback (see TODO in parent).
        self.real_light_lux     = val("shortwave_radiation", 0.0)
        self.real_soil_moisture = round(val("soil_moisture_0_to_1cm", 0.3), 3)

    # ------------------------------------------------------------------
    # STATUS — default: always "ok" (see bad_status_prob docstring)
    # ------------------------------------------------------------------

    def _random_status(self, bad_values: list) -> str:
        if random.random() < self.bad_status_prob:
            return random.choice(bad_values)
        return "ok"

    # ------------------------------------------------------------------
    # RUN LOOP — advance the simulated clock, then publish as usual
    # ------------------------------------------------------------------

    def run(self):
        print(f"[SimHourly] Publishing every {self.interval}s. "
              f"1 real second = {self.time_scale:.0f} simulated seconds. "
              f"Ctrl+C to stop.")
        while True:
            elapsed_sim_hours = int((time.time() - self.t0) * self.time_scale // 3600)
            self._apply_hour(elapsed_sim_hours)

            print(f"[SimHourly] sim hour: {self.sim_time_label}  "
                  f"temp={self.real_temperature}C  "
                  f"irradiation={self.real_light_lux}W/m2  "
                  f"wind_10m={self.real_wind_10m}km/h")

            self.publish_p03_bme280()
            self.publish_p03_light()
            self.publish_p01()
            self.publish_p07()
            time.sleep(self.interval)


if __name__ == "__main__":
    sim = EnvironmentSimulatorHourly(
        broker="broker.hivemq.com",
        port=1883,
        interval=5,
        time_scale=900,
    )
    sim.run()
