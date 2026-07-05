import json
import time
import random
import datetime
import requests
import paho.mqtt.client as mqtt


class EnvironmentSimulator:
    """
    Simulates P01, P03, and P07 hardware by publishing realistic MQTT messages.

    Instead of random.uniform() for everything, we now fetch live weather data
    from OpenMeteo on startup and use those values as the baseline for each
    reading. Small random noise is added each cycle so readings look like a
    live sensor rather than a frozen flat line.

    Re-fetches from OpenMeteo every 10 minutes so data stays fresh over a
    long test run without hammering the API every 5 seconds.
    """

    TOPICS = {
        "p03_bme280": "cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature",
        "p03_light":  "cps/p03/DDATA/sensor-main/ambient-light",
        "p01":        "cps/p01/DDATA/sensor-main/soil_moisture",
        "p07":        "cps/p07/DDATA/weather-pipeline",
    }

    OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
    OPENMETEO_LAT = 52.52    # Berlin (TU Berlin)
    OPENMETEO_LON = 13.405

    def __init__(self, broker: str, port: int, interval: int = 5):
        self.interval = interval
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.connect(broker, port)
        self.client.loop_start()

        # Fetch real weather data from OpenMeteo before the first publish.
        self._fetch_openmeteo()

    # ------------------------------------------------------------------
    # OPENMETEO FETCH
    # ------------------------------------------------------------------

    def _fetch_openmeteo(self):
        """
        Fetches current weather and hourly soil moisture from OpenMeteo.
        Stores results as instance variables used by all publish methods.

        If the request fails (no internet, API down), safe defaults are used
        so the simulator keeps running instead of crashing.
        """
        print("[Sim] Fetching live data from OpenMeteo...")
        try:
            params = {
                "latitude":      self.OPENMETEO_LAT,
                "longitude":     self.OPENMETEO_LON,
                # All in one request — OpenMeteo accepts comma-separated variables.
                "current":       "temperature_2m,relative_humidity_2m,"
                                 "surface_pressure,wind_speed_10m,shortwave_radiation",
                "hourly":        "soil_moisture_0_to_1cm",
                "forecast_days": 1,
            }
            response = requests.get(self.OPENMETEO_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # ---- current weather fields ----
            current = data["current"]
            self.real_temperature = current["temperature_2m"]        # °C
            self.real_humidity    = current["relative_humidity_2m"]  # %
            self.real_pressure    = current["surface_pressure"]      # hPa
            self.real_wind_10m    = current["wind_speed_10m"]        # km/h at 10 m

            # Convert solar radiation (W/m²) to lux.
            # Rule of thumb for natural daylight: 1 W/m² ≈ 120 lux.
            # Clamped to BH1750 sensor maximum of 65 535 lux.
            #TODO:
            # The input to the simulation should be in J which can be easily
            # calculated with W/m^2. It is also physical value.
            # Use W/m^2 and change names to irradiation. Dont mention lux. -Berkin
            radiation           = current["shortwave_radiation"]      # W/m²
            self.real_light_lux = radiation #min(round(radiation * 120, 1), 65535.0)


            # ---- hourly soil moisture ----
            # OpenMeteo gives soil_moisture_0_to_1cm as a list aligned to hourly
            # timestamps. We find the current UTC hour's index to get today's value.
            hourly       = data["hourly"]
            current_hour = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
            try:
                idx = hourly["time"].index(current_hour)
                self.real_soil_moisture = round(hourly["soil_moisture_0_to_1cm"][idx], 3)
            except (ValueError, IndexError):
                # Hour string not found in the list — unlikely but handled safely.
                self.real_soil_moisture = 0.3

            print(
                f"[Sim] Data fetched:  temp={self.real_temperature}°C  "
                f"humidity={self.real_humidity}%  pressure={self.real_pressure}hPa  "
                f"light={self.real_light_lux}lux  wind_10m={self.real_wind_10m}km/h  "
                f"soil={self.real_soil_moisture}"
            )

        except (requests.RequestException, KeyError, ValueError) as e:
            # OpenMeteo is unreachable or returned unexpected data.
            # Use safe defaults so the simulator still runs.
            print(f"[Sim] OpenMeteo fetch failed: {e}. Using safe defaults.")
            self.real_temperature   = 18.0
            self.real_humidity      = 60.0
            self.real_pressure      = 1013.0
            self.real_wind_10m      = 10.0
            self.real_light_lux     = 5000.0
            self.real_soil_moisture = 0.3

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _now(self) -> str:
        return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _random_status(self, bad_values: list) -> str:
        """
        Weighted random status. "ok" appears four times so it is picked
        roughly 80 % of the time; each bad status appears once.
        """
        pool = ["ok", "ok", "ok", "ok"] + bad_values
        return random.choice(pool)

    # ------------------------------------------------------------------
    # P03 -- BME280: temperature, humidity, pressure
    # ------------------------------------------------------------------

    def publish_p03_bme280(self):
        status = self._random_status(["sensor_error", "out_of_range", "stale"])

        if status == "ok":
            # Use real OpenMeteo values as the baseline and add tiny noise.
            # Noise ranges: ±0.3 °C, ±1 %, ±0.5 hPa — realistic sensor jitter.
            temperature_c = round(self.real_temperature + random.uniform(-0.3, 0.3), 1)
            humidity_rel  = round(max(0.0, min(100.0,
                                   self.real_humidity + random.uniform(-1.0, 1.0))), 1)
            pressure_hpa  = round(self.real_pressure + random.uniform(-0.5, 0.5), 1)
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

    # ------------------------------------------------------------------
    # P03 -- BH1750: ambient light
    # ------------------------------------------------------------------

    def publish_p03_light(self):
        status = self._random_status(["sensor_error", "out_of_range", "stale"])

        if status == "ok":
            # Add ±5 % noise around the real radiation-derived lux value.
            noise     = random.uniform(0.95, 1.05)
            light_lux = round(min(self.real_light_lux * noise, 65535.0), 1)
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
        status = self._random_status(["sensor_disconnected", "out_of_range"])

        if status == "ok":
            # Small noise (±0.01) around the real soil moisture fraction.
            # Clamped to the valid range [0.0, 1.0].
            calibrated = round(max(0.0, min(1.0,
                               self.real_soil_moisture + random.uniform(-0.01, 0.01))), 3)

            # Derive raw_adc from calibrated.
            # Resistive soil sensors work inversely: dry soil = high resistance =
            # high ADC reading; wet soil = low resistance = low ADC reading.
            # Formula: raw_adc ≈ (1 - calibrated) × 65535, plus small noise.
            raw_adc = int(max(0, min(65535,
                          (1.0 - calibrated) * 65535 + random.uniform(-500, 500))))
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
    # P07 -- Weather forecast
    # ------------------------------------------------------------------

    def publish_p07(self):
        """
        P07 publishes a rich weather payload including a forecast array and
        daily ET summary. We now use real_temperature and real_wind_10m as
        baselines so the simulated forecast data is grounded in reality.

        wind_speed is included here because P07 will publish it on this same
        topic once they configure their pipeline.
        """
        status = random.choice(["live", "live", "live", "live", "cached", "unavailable"])

        location = {
            "name":      "berlin",
            "latitude":  self.OPENMETEO_LAT,
            "longitude": self.OPENMETEO_LON,
        }

        if status == "unavailable":
            forecast_hours   = []
            daily_et_summary = []
            wind_speed       = None  # no value when P07 has no data
        else:
            # Forecast hours: use real temperature as the baseline, add ±3 °C
            # variation to simulate natural change across the next few hours.
            forecast_hours = []
            for i in range(3):
                hour_time = datetime.datetime.utcnow() + datetime.timedelta(hours=i)
                forecast_hours.append({
                    "time":                hour_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "temperature_c":       round(self.real_temperature + random.uniform(-3.0, 3.0), 1),
                    "precipitation_mm":    round(random.uniform(0.0, 2.0), 2),
                    # Convert real lux back to W/m² for the forecast radiation field.
                    "solar_radiation_wm2": round(max(0.0,
                                             self.real_light_lux / 120 + random.uniform(-50, 50)), 1),
                })

            # Daily ET summary: max/min are offset from the real temperature.
            daily_et_summary = [{
                "date":                   datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "hours_of_data":          3,
                "temp_max_c":             round(self.real_temperature + random.uniform(2.0, 5.0), 1),
                "temp_min_c":             round(self.real_temperature - random.uniform(2.0, 5.0), 1),
                "temp_mean_c":            round(self.real_temperature + random.uniform(-1.0, 1.0), 1),
                "total_precipitation_mm": round(random.uniform(0.0, 5.0), 2),
                "total_solar_mj_m2":      round(random.uniform(0.0, 20.0), 2),
                "ra_mj_m2":               round(random.uniform(5.0, 35.0), 2),
                "et0_mm":                 round(random.uniform(0.5, 6.0), 2),
            }]

            # Wind speed at 2 m — same baseline and formula as the pipeline's
            # WeatherFallback.get_wind_speed() so both stay consistent.
            wind_speed = round(max(0.0, self.real_wind_10m + random.uniform(-1.0, 1.0)), 1)

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

        # wind_speed is only included when P07 has valid data.
        if wind_speed is not None:
            payload["wind_speed"] = wind_speed

        if status == "unavailable":
            payload["weather/message"] = "Simulated unavailable: cache too old or missing."

        et0_values = [d["et0_mm"] for d in daily_et_summary]
        print(f"[Sim P07] status={status}  wind_10m={wind_speed}km/h  et0={et0_values}")
        self.client.publish(self.TOPICS["p07"], json.dumps(payload))

    # ------------------------------------------------------------------
    # RUN LOOP
    # ------------------------------------------------------------------

    def run(self):
        """
        Publishes one round of messages, waits interval seconds, repeats.
        Re-fetches from OpenMeteo every 120 cycles (10 minutes at 5s interval)
        so simulated values stay close to reality over a long test run.
        """
        print("[Sim] Starting publish loop. Ctrl+C to stop.")
        cycle = 0
        while True:
            # Refresh every 120 cycles — often enough to stay fresh,
            # rarely enough not to abuse the free OpenMeteo API.
            if cycle > 0 and cycle % 120 == 0:
                self._fetch_openmeteo()

            self.publish_p03_bme280()
            self.publish_p03_light()
            self.publish_p01()
            self.publish_p07()
            time.sleep(self.interval)
            cycle += 1


if __name__ == "__main__":
    sim = EnvironmentSimulator(
        broker="broker.hivemq.com",
        port=1883,
        interval=5,
    )
    sim.run()
