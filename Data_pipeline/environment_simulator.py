import json
import time
import random
import datetime
import paho.mqtt.client as mqtt


class EnvironmentSimulator:
    """
    This class pretends to be the real hardware from P01, P03, and P07.
    In a real deployment, each of those groups runs their own device.
    Here, we fake their messages so we can test our pipeline without
    needing anyone else's hardware to be running.

    Each group publishes ONE message per cycle to ONE topic.
    All their fields travel together in that single message -- that is
    why each publish method builds one dict and calls client.publish once.
    """

    # Each group owns one topic. We store them here so if a topic changes
    # we only update one place, not every method that uses it.
    TOPICS = {
    "p03_bme280": "cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature",
    "p03_light":  "cps/p03/DDATA/sensor-main/ambient-light",
    "p01":        "cps/p01/DDATA/sensor-main/soil_moisture",
    "p07":        "cps/p07/DDATA/weather-pipeline",
}

    def __init__(self, broker: str, port: int, interval: int = 5):
        self.interval = interval
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.connect(broker, port)
        # loop_start() keeps the network connection alive in the background
        # so that publish() calls below don't get dropped. We use loop_start
        # and not loop_forever because we still need to run our own while True
        # loop underneath -- loop_forever would block and we'd never reach it.
        self.client.loop_start()

    # ------------------------------------------------------------------
    # HELPER: current UTC timestamp as an ISO 8601 string
    # ------------------------------------------------------------------
    def _now(self) -> str:
        """
        Every message from every group includes a timestamp so the pipeline
        and any downstream consumer knows exactly when the reading was taken.
        ISO 8601 is the agreed format across all groups (e.g. 2025-06-26T14:00:00Z).
        """
        return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # HELPER: pick a random status, weighted toward "ok"
    # ------------------------------------------------------------------
    def _random_status(self, bad_values: list) -> str:
        """
        Real sensors fail occasionally but not constantly. To simulate this,
        "ok" appears four times in the pool so it is picked most of the time.
        The bad statuses appear once each -- rare but possible.
        bad_values is passed in because each group uses different status words.
        """
        pool = ["ok", "ok", "ok", "ok"] + bad_values
        return random.choice(pool)

    # ------------------------------------------------------------------
    # P03 -- Environmental sensor (temperature, humidity, pressure, light)
    # ------------------------------------------------------------------
    def publish_p03_bme280(self):
        status = self._random_status(["sensor_error", "out_of_range", "stale"])

        if status == "ok":
            temperature_c = round(random.uniform(-40.0, 85.0), 1)
            humidity_rel  = round(random.uniform(0.0, 100.0), 1)
            pressure_hpa  = round(random.uniform(300.0, 1100.0), 1)
        else:
            temperature_c = None
            humidity_rel  = None
            pressure_hpa  = None

        payload = {
            "timestamp":     self._now(),
            "temperature_c": temperature_c,
            "humidity_rel":  humidity_rel,
            "pressure_hpa":  pressure_hpa,
            "status":        status,
        }

        self.client.publish(self.TOPICS["p03_bme280"], json.dumps(payload))
        print(f"[Sim P03 BME280] {payload}")

    def publish_p03_light(self):
        status = self._random_status(["sensor_error", "out_of_range", "stale"])

        if status == "ok":
            light_lux = round(random.uniform(0.0, 65535.0), 1)
        else:
            light_lux = None

        payload = {
            "timestamp": self._now(),
            "light_lux": light_lux,
            "status":    status,
        }

        self.client.publish(self.TOPICS["p03_light"], json.dumps(payload))
        print(f"[Sim P03 Light] {payload}")

    # ------------------------------------------------------------------
    # P01 -- Soil moisture sensor
    # ------------------------------------------------------------------
    def publish_p01(self):
        """
        P01 publishes both the processed value (calibrated, 0.0-1.0) and
        the raw hardware reading (raw_adc, 0-65536). The raw value is kept
        for drift detection -- over time, if raw_adc drifts while calibrated
        stays stable, it can signal that the sensor needs recalibration.
        Again, when status is bad, numeric values go to None.
        """
        status = self._random_status(["sensor_disconnected", "out_of_range"])

        if status == "ok":
            calibrated = round(random.uniform(0.0, 1.0), 3)
            # raw_adc is an integer (ADC bit value), so we use randint not uniform.
            # randint(a, b) returns a whole number between a and b inclusive.
            raw_adc = random.randint(0, 65536)
        else:
            calibrated = None
            raw_adc    = None

        payload = {
            "timestamp":  self._now(),
            "calibrated": calibrated,
            "raw_adc":    raw_adc,
            "status":     status,
        }

        self.client.publish(self.TOPICS["p01"], json.dumps(payload))
        print(f"[Sim P01] {payload}")

    # ------------------------------------------------------------------
    # P07 -- Weather forecast (simulated, not a real API call)
    # ------------------------------------------------------------------
    def publish_p07(self):
        """
        P07's payload is much richer than the sensor groups. It contains
        nested objects (location, staleness) and arrays (forecast_hours,
        daily_et_summary). In a real deployment, P07 would call OpenMeteo
        and fill these with real forecast data. Here we generate fake but
        structurally correct values so the pipeline can parse the shape.

        Three possible statuses:
          "live"        -- freshly fetched from OpenMeteo this cycle
          "cached"      -- API was unreachable, using a saved local file
          "unavailable" -- cache is too old (>24h) or missing entirely;
                          forecast_hours and daily_et_summary must be empty
        """
        # P07 never uses "ok" -- its valid statuses are live/cached/unavailable.
        # We weight toward "live" the same way _random_status weights toward "ok".
        status = random.choice(["live", "live", "live", "live", "cached", "unavailable"])

        # location is a nested dict, not a plain string.
        # The pipeline reads latitude and longitude from here to update
        # WeatherFallback so it can make accurate OpenMeteo calls.
        location = {
            "name":      "berlin",
            "latitude":  52.52,
            "longitude": 13.405,
        }

        if status == "unavailable":
            # When unavailable, the spec requires empty arrays for these two.
            # Sending fake data here would be wrong -- the pipeline must not
            # act on forecast data it cannot trust.
            forecast_hours   = []
            daily_et_summary = []
        else:
            # Build a small fake hourly forecast (3 hours, not 48, to keep
            # the output readable in the terminal during testing).
            forecast_hours = []
            for i in range(3):
                hour_time = datetime.datetime.utcnow() + datetime.timedelta(hours=i)
                forecast_hours.append({
                    "time":                hour_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "temperature_c":       round(random.uniform(10.0, 35.0), 1),
                    "precipitation_mm":    round(random.uniform(0.0, 5.0), 2),
                    "solar_radiation_wm2": round(random.uniform(0.0, 900.0), 1),
                })

            # One daily summary entry covering today.
            # et0_mm is the key value the irrigation controller (P05) needs.
            # The Hargreaves-Samani formula produces typical values of 0-15 mm/day.
            daily_et_summary = [{
                "date":                   datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "hours_of_data":          3,
                "temp_max_c":             round(random.uniform(20.0, 35.0), 1),
                "temp_min_c":             round(random.uniform(5.0, 15.0), 1),
                "temp_mean_c":            round(random.uniform(12.0, 25.0), 1),
                "total_precipitation_mm": round(random.uniform(0.0, 20.0), 2),
                "total_solar_mj_m2":      round(random.uniform(0.0, 30.0), 2),
                "ra_mj_m2":               round(random.uniform(5.0, 40.0), 2),
                "et0_mm":                 round(random.uniform(0.0, 10.0), 2),
            }]

        # staleness describes how fresh the data is. is_cached tells the
        # consumer whether this came from a live API call or a saved file.
        is_cached = (status == "cached")
        staleness = {
            "is_cached":  is_cached,
            "fetched_at": self._now(),
            "hours_old":  round(random.uniform(0.0, 23.0), 1) if is_cached else 0.0,
        }

        payload = {
            "weather/data_source":      "open-meteo",
            "weather/location":         json.dumps(location),
            "weather/forecast_hours":   json.dumps(forecast_hours),
            "weather/daily_et_summary": json.dumps(daily_et_summary),
            "weather/staleness":        json.dumps(staleness),
            "weather/status":           status,
        }

        # Only include "message" when status is unavailable -- the spec says
        # this field is absent in live/cached messages.
        if status == "unavailable":
            payload["weather/message"] = "Simulated unavailable: cache too old or missing."

        et0_values = [d["et0_mm"] for d in daily_et_summary]
        print(f"[Sim P07] status={status}, et0={et0_values}")
        self.client.publish(self.TOPICS["p07"], json.dumps(payload))

    # ------------------------------------------------------------------
    # RUN LOOP
    # ------------------------------------------------------------------
    def run(self):
        """
        Publishes one round of messages from all three groups, then waits
        interval seconds before repeating. In real life each group runs on
        their own device on their own schedule -- here we fire them all at
        once for simplicity.
        """
        print("[Sim] Starting publish loop. Ctrl+C to stop.")
        while True:
            self.publish_p03_bme280()
            self.publish_p03_light()
            self.publish_p01()
            self.publish_p07()
            time.sleep(self.interval)


if __name__ == "__main__":
    sim = EnvironmentSimulator(
        broker="broker.hivemq.com",
        port=1883,
        interval=5,
    )
    sim.run()
