import csv
import json
import os
import time
import requests
import paho.mqtt.client as mqtt


# =============================================================================
# SCHEMAS
# Each schema maps one MQTT topic to the fields that topic carries.
# Field types:
#   "range"  → numeric, validated against (min, max)
#   "enum"   → string, must be one of valid_values
#   "string" → free-form text, checked to be a str
#   "object" → nested dict  (e.g. location, staleness from P07)
#   "array"  → list of items (e.g. forecast_hours from P07)
# =============================================================================

ENVIRONMENT_SCHEMA = {
    "cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature": {
        "timestamp":     {"type": "string"},
        "temperature_c": {"type": "range", "valid_range": (-40.0, 85.0)},
        "humidity_rel":  {"type": "range", "valid_range": (0.0, 100.0)},
        "pressure_hpa":  {"type": "range", "valid_range": (300.0, 1100.0)},
        "status":        {"type": "enum",
                          "valid_values": ["ok", "sensor_error", "out_of_range", "stale"]},
    },
    "cps/p03/DDATA/sensor-main/ambient-light": {
        "timestamp":  {"type": "string"},
        "light_lux":  {"type": "range", "valid_range": (0.0, 65535.0)},
        "status":     {"type": "enum",
                       "valid_values": ["ok", "sensor_error", "out_of_range", "stale"]},
    },
}

SOIL_MOISTURE_SCHEMA = {
    "cps/p01/DDATA/sensor-main/soil_moisture": {
        "timestamp":  {"type": "string"},
        "calibrated": {"type": "range", "valid_range": (0.0, 1.0)},
        "raw_adc":    {"type": "range", "valid_range": (0, 65536)},
        "status":     {"type": "enum",
                       "valid_values": ["ok", "sensor_disconnected", "out_of_range"]},
    },
}

# P07 uses "weather/status" (not "status") and sends location/staleness as
# JSON strings inside the payload — they are decoded to dicts in _on_message.
WEATHER_API_SCHEMA = {
    "cps/p07/DDATA/weather-pipeline": {
        "weather/data_source":      {"type": "enum",   "valid_values": ["open-meteo"]},
        "weather/location":         {"type": "object"},
        "weather/forecast_hours":   {"type": "array"},
        "weather/daily_et_summary": {"type": "array"},
        "weather/staleness":        {"type": "object"},
        "weather/status":           {"type": "enum",
                                     "valid_values": ["live", "cached", "unavailable"]},
        "weather/message":          {"type": "string"},
        # P07 will publish wind_speed on this topic once configured.
        "wind_speed":               {"type": "range", "valid_range": (0.0, 150.0)},
    },
}

SCHEMA = {
    **ENVIRONMENT_SCHEMA,
    **SOIL_MOISTURE_SCHEMA,
    **WEATHER_API_SCHEMA,
}

# Short labels used in terminal output — one label per topic.
TOPIC_LABEL = {
    "cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature": "P03",
    "cps/p03/DDATA/sensor-main/ambient-light":                     "P03",
    "cps/p01/DDATA/sensor-main/soil_moisture":                     "P01",
    "cps/p07/DDATA/weather-pipeline":                              "P07",
}

# Status values that mean "do not trust this reading" for P01/P03.
# P07 uses different vocabulary (live/cached/unavailable), extracted separately.
BAD_STATUSES = {"sensor_disconnected", "sensor_error", "out_of_range", "stale", "unavailable"}

MAX_LOG_HOURS = 8
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_log.csv")


# =============================================================================
# WeatherFallback
# Plan B for sensor fields when P03/P01 cannot be trusted.
# Calls OpenMeteo using GPS coordinates that P07 delivers at runtime.
# Coordinates start as None and are updated on the first P07 message.
# =============================================================================
class WeatherFallback:
    def __init__(self, latitude, longitude):
        self.latitude  = latitude
        self.longitude = longitude
        self.url = "https://api.open-meteo.com/v1/forecast"

    def _coords_ready(self):
        return self.latitude is not None and self.longitude is not None

    def get_temperature(self):
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params   = {"latitude": self.latitude, "longitude": self.longitude,
                        "current": "temperature_2m"}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            return response.json()["current"]["temperature_2m"]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo temperature failed: {e}")
            return None

    def get_humidity(self):
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params   = {"latitude": self.latitude, "longitude": self.longitude,
                        "current": "relative_humidity_2m"}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            return response.json()["current"]["relative_humidity_2m"]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo humidity failed: {e}")
            return None

    def get_pressure(self):
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params = {"latitude": self.latitude, "longitude": self.longitude,
                      "current": "surface_pressure"}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            return response.json()["current"]["surface_pressure"]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo pressure failed: {e}")
            return None

    def get_wind_speed(self):
        # OpenMeteo only provides wind speed at 10 m (meteorological standard height).
        # We need 2 m (balcony level), so we convert using the Wind Power Law:
        #
        #   v(z) = v(z_ref) × (z / z_ref) ^ α
        #
        # where:
        #   v(z)     = wind speed at target height   → 2 m
        #   v(z_ref) = wind speed at reference height → 10 m  (from OpenMeteo)
        #   α        = wind shear exponent, depends on terrain roughness:
        #                0.14  open flat land
        #                0.25  suburban / urban  ← our case (Berlin balcony)
        #                0.40  dense city centre
        #
        # (2 / 10) ^ 0.25 ≈ 0.669 → 2 m speed is roughly 67 % of 10 m speed.
        #
        # Note: a balcony is shielded by its building and affected by neighbours —
        # no formula captures that geometry. Treat this as an approximation until
        # P07's anemometer provides a real 2 m reading.
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params = {"latitude": self.latitude, "longitude": self.longitude,
                      "current": "wind_speed_10m"}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            wind_10m = response.json()["current"]["wind_speed_10m"]  # km/h at 10 m
            alpha    = 0.25
            wind_2m  = wind_10m * (2 / 10) ** alpha
            return round(wind_2m, 1)
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo wind_speed failed: {e}")
            return None

    def get_light_lux(self):
        # OpenMeteo provides shortwave radiation in W/m².
        # Approximation: 1 W/m² ≈ 120 lux for natural daylight.
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params = {"latitude": self.latitude, "longitude": self.longitude,
                      "current": "shortwave_radiation"}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            radiation = response.json()["current"]["shortwave_radiation"]  # W/m²
            lux = round(radiation * 120, 1)
            return min(lux, 65535.0)  # clamp to BH1750 hardware max
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo light_lux failed: {e}")
            return None

    def get_soil_moisture(self):
        # OpenMeteo hourly soil moisture (0–1 cm depth) in m³/m³.
        # Range 0.05 (dry) to 0.45 (saturated) — fits within calibrated's valid range.
        # Used only when last_known runs out (> MAX_TOLERATED_MISSES consecutive misses).
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params = {"latitude": self.latitude, "longitude": self.longitude,
                      "hourly": "soil_moisture_0_to_1cm",
                      "forecast_days": 1}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            hourly = response.json()["hourly"]
            current_hour = time.strftime("%Y-%m-%dT%H:00", time.gmtime())
            idx = hourly["time"].index(current_hour)
            return round(hourly["soil_moisture_0_to_1cm"][idx], 3)
        except (requests.RequestException, KeyError, ValueError, IndexError) as e:
            print(f"[Fallback] OpenMeteo soil_moisture failed: {e}")
            return None


# =============================================================================
# LastKnownValueFallback
# Returns the last trusted reading for a field. Used as Plan B for soil
# moisture — acceptable for short gaps because soil dries slowly.
# =============================================================================
class LastKnownValueFallback:
    def __init__(self, cache: dict):
        self.cache = cache  # shared reference to pipeline.last_raw_values

    def get_last_value(self, field_name: str):
        return self.cache.get(field_name)


# =============================================================================
# EnvironmentPipeline
# Subscribes to every topic in SCHEMA, validates each field, and runs the
# Plan A → B → C fallback chain for all numeric fields.
# =============================================================================
class EnvironmentPipeline:

    # Fallback strategy assigned to each numeric field.
    # "weather"     → query OpenMeteo when sensor fails
    # "last_known"  → use last trusted reading for up to MAX_TOLERATED_MISSES
    # "no_fallback" → no external source; escalate immediately if sensor fails
    FIELD_FALLBACK_STRATEGY = {
        "temperature_c":  "weather",
        "humidity_rel":   "weather",
        "pressure_hpa":   "weather",
        "wind_speed":     "weather",
        "light_lux":      "weather",
        "calibrated":     "last_known",  # after 5 misses, falls back to OpenMeteo soil moisture
        "raw_adc":        "no_fallback",
    }

    def __init__(self, broker: str, port: int, weather_fallback: WeatherFallback,
                 window_seconds: float = 300, connect: bool = True):
        self.weather_fallback = weather_fallback
        self.window_seconds   = window_seconds

        self.p01_timestamp = None  # timestamp of the most recent P01 message

        self.value_buffer    = {}  # {field: [(unix_time, value), ...]}  rolling window
        self.last_raw_values = {}  # {field: value}  exact last trusted reading
        self.latest_values   = {}  # {field: value}  what get_data() returns

        self.last_known_fallback  = LastKnownValueFallback(self.last_raw_values)
        self.consecutive_misses   = {}
        self.MAX_TOLERATED_MISSES = 5

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        if connect:
            self.client.connect(broker, port)

    # -------------------------------------------------------------------------
    # MQTT CALLBACKS
    # -------------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            print("[Pipeline] Connected.")
            for topic in SCHEMA:
                client.subscribe(topic)
                print(f"[Pipeline] Subscribed: {topic}")
        else:
            print(f"[Pipeline] Connection failed: {reason_code}")

    def _on_message(self, client, userdata, message):
        topic = message.topic
        field_definitions = SCHEMA.get(topic)
        if field_definitions is None:
            print(f"[Pipeline] Unknown topic: {topic}")
            return

        try:
            data = json.loads(message.payload.decode())

            # Capture P01's timestamp right here — before P03 or P07 messages
            # can arrive and overwrite latest_values["timestamp"].
            if topic == "cps/p01/DDATA/sensor-main/soil_moisture":
                self.p01_timestamp = data.get("timestamp")

        except json.JSONDecodeError:
            self._escalate(topic, "malformed JSON payload")
            return

        # P07 sends some nested fields as JSON strings inside the payload.
        # Decode them to proper dicts/lists before processing.
        if topic == "cps/p07/DDATA/weather-pipeline":
            for nested_field in ["weather/location", "weather/staleness",
                                  "weather/forecast_hours", "weather/daily_et_summary"]:
                raw = data.get(nested_field)
                if isinstance(raw, str):
                    try:
                        data[nested_field] = json.loads(raw)
                    except json.JSONDecodeError:
                        self._escalate(topic, f"{nested_field} contained invalid JSON string")
                        return

        # P07 uses "weather/status" instead of "status".
        if topic == "cps/p07/DDATA/weather-pipeline":
            status = data.get("weather/status")
        else:
            status = data.get("status")

        for field_name, rules in field_definitions.items():
            if field_name == "status" and topic != "cps/p07/DDATA/weather-pipeline":
                continue
            value = data.get(field_name)
            self._process_field(topic, field_name, value, status, rules)

        # Print one summary line per message — only numeric range fields shown.
        label = TOPIC_LABEL.get(topic, topic)
        numeric_fields = {
            fn: data.get(fn)
            for fn, rules in field_definitions.items()
            if rules["type"] == "range" and data.get(fn) is not None
        }
        if numeric_fields:
            parts = "  ".join(f"{k}={v}" for k, v in numeric_fields.items())
            print(f"[{label}] status={status}  {parts}")

    # -------------------------------------------------------------------------
    # FIELD ROUTING
    # -------------------------------------------------------------------------

    def _process_field(self, topic, field_name, value, status, rules):
        field_type = rules["type"]

        if field_type == "range":
            self._run_fallback_chain(topic, field_name, value, status, rules["valid_range"])
        elif field_type == "enum":
            self._validate_enum(topic, field_name, value, rules["valid_values"])
        elif field_type == "string":
            self._validate_string(topic, field_name, value)
        elif field_type == "object":
            self._validate_object(topic, field_name, value)
        elif field_type == "array":
            self._validate_array(topic, field_name, value)
        else:
            print(f"[Pipeline] Unknown field type '{field_type}' for {field_name}")

    # -------------------------------------------------------------------------
    # VALIDATION METHODS
    # -------------------------------------------------------------------------

    def _validate_enum(self, topic, field_name, value, valid_values):
        if value in valid_values:
            self.latest_values[field_name] = value
        else:
            self._escalate(topic, f"{field_name}='{value}' not in {valid_values}")

    def _validate_string(self, topic, field_name, value):
        if value is None:
            return
        if isinstance(value, str):
            self.latest_values[field_name] = value
        else:
            self._escalate(topic, f"{field_name} expected str, got {type(value).__name__}")

    def _validate_object(self, topic, field_name, value):
        if value is None:
            return
        if not isinstance(value, dict):
            self._escalate(topic, f"{field_name} expected dict, got {type(value).__name__}")
            return
        self.latest_values[field_name] = value

        # P07's location carries GPS coordinates that WeatherFallback needs.
        # Update on every P07 message so coordinates stay current.
        if field_name == "location":
            lat = value.get("latitude")
            lng = value.get("longitude")
            if lat is not None and lng is not None:
                self.weather_fallback.latitude  = lat
                self.weather_fallback.longitude = lng
            else:
                print("[WARNING] P07 location missing latitude/longitude keys.")

    def _validate_array(self, topic, field_name, value):
        if value is None:
            return
        if not isinstance(value, list):
            self._escalate(topic, f"{field_name} expected list, got {type(value).__name__}")
            return
        self.latest_values[field_name] = value

    # -------------------------------------------------------------------------
    # PLAN A → B → C FALLBACK CHAIN
    #
    # Plan A: use the sensor reading if status is clean and value is in range.
    # Plan B: use the fallback source assigned to this field (see FIELD_FALLBACK_STRATEGY).
    # Plan C: all sources failed → escalate to error log.
    # -------------------------------------------------------------------------

    def _run_fallback_chain(self, topic, field_name, value, status, valid_range):
        # Plan A
        in_range = True
        if valid_range is not None and value is not None:
            in_range = valid_range[0] <= value <= valid_range[1]

        status_ok = (status is None) or (status not in BAD_STATUSES)

        if status_ok and value is not None and in_range:
            self._record_good_value(field_name, value)
            self.consecutive_misses[field_name] = 0
            return

        # Plan B
        strategy       = self.FIELD_FALLBACK_STRATEGY.get(field_name, "no_fallback")
        fallback_value = None

        if strategy == "weather":
            if field_name == "temperature_c":
                fallback_value = self.weather_fallback.get_temperature()
            elif field_name == "humidity_rel":
                fallback_value = self.weather_fallback.get_humidity()
            elif field_name == "pressure_hpa":
                fallback_value = self.weather_fallback.get_pressure()
            elif field_name == "wind_speed":
                fallback_value = self.weather_fallback.get_wind_speed()
            elif field_name == "light_lux":
                fallback_value = self.weather_fallback.get_light_lux()
            if fallback_value is not None:
                print(f"[WARNING] {field_name}: sensor status='{status}', using OpenMeteo fallback = {fallback_value}")

        elif strategy == "last_known":
            self.consecutive_misses[field_name] = (
                self.consecutive_misses.get(field_name, 0) + 1
            )
            miss_count = self.consecutive_misses[field_name]
            if miss_count <= self.MAX_TOLERATED_MISSES:
                fallback_value = self.last_known_fallback.get_last_value(field_name)
                print(f"[WARNING] {field_name}: sensor status='{status}', "
                      f"miss #{miss_count}/{self.MAX_TOLERATED_MISSES}, "
                      f"using last known = {fallback_value}")
            else:
                print(f"[WARNING] {field_name}: {miss_count} consecutive misses, exceeded limit.")
                if field_name == "calibrated":
                    fallback_value = self.weather_fallback.get_soil_moisture()
                    if fallback_value is not None:
                        print(f"[WARNING] {field_name}: using OpenMeteo soil moisture as secondary fallback = {fallback_value}")

        if fallback_value is not None:
            self._record_good_value(field_name, fallback_value)
            return

        # Plan C
        self._escalate(topic, f"{field_name} unavailable from sensor and all fallbacks")

    # -------------------------------------------------------------------------
    # ROLLING BUFFER
    # -------------------------------------------------------------------------
    # Called at the end of every successful fallback chain — whenever a value passes
    # Plan A (sensor ok) or is saved by Plan B (fallback). Stores the trusted value
    # in four places:
    #   1. last_raw_values  → exact last reading, used by LastKnownValueFallback
    #   2. latest_values    → what get_data() returns
    #   3. sensor_log.csv   → 8-hour history on disk
    #   4. value_buffer     → rolling window for get_average()
    # Also trims value_buffer immediately so it never grows beyond window_seconds.
    def _record_good_value(self, field_name: str, value: float):
        now = time.time()

        self.last_raw_values[field_name] = value
        self.latest_values[field_name]   = value
        self._log_to_csv(field_name, value, now)

        # value_buffer stores (unix_time, value) pairs in a rolling window.
        # setdefault creates the list on first write — no need to pre-populate.
        self.value_buffer.setdefault(field_name, []).append((now, value))

        cutoff = now - self.window_seconds
        self.value_buffer[field_name] = [
            (t, v) for (t, v) in self.value_buffer[field_name] if t >= cutoff
        ]

    # -------------------------------------------------------------------------
    # CSV LOGGING
    # -------------------------------------------------------------------------

    def _log_to_csv(self, field_name: str, value: float, timestamp: float):
        # When the log reaches MAX_LOG_HOURS, delete it and start a fresh file.
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                reader = csv.reader(f)
                next(reader, None)          # skip header
                first_row = next(reader, None)
            if first_row is not None:
                hours_stored = (timestamp - float(first_row[0])) / 3600
                if hours_stored >= MAX_LOG_HOURS:
                    os.remove(LOG_FILE)
                    print("[Log] 8-hour limit reached. Old log deleted, starting fresh.")

        file_exists = os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp_unix", "timestamp_utc", "field", "value"])
            utc_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime(timestamp))
            writer.writerow([timestamp, utc_str, field_name, value])

    # -------------------------------------------------------------------------
    # PUBLIC ACCESSORS
    # -------------------------------------------------------------------------

    def get_average(self, field_name: str):
        """Rolling average of all trusted readings within the last window_seconds."""
        if field_name not in self.value_buffer:
            return None
        now    = time.time()
        cutoff = now - self.window_seconds
        recent = [v for (t, v) in self.value_buffer[field_name] if t >= cutoff]
        return sum(recent) / len(recent) if recent else None

    def get_data(self, field_name: str = None):
        """Returns the latest trusted value for one field, or all fields as a dict."""
        if field_name is not None:
            return self.latest_values.get(field_name)
        return dict(self.latest_values)

    def get_p01_timestamp(self):
        """Returns the ISO timestamp from the most recent P01 soil moisture message."""
        return self.p01_timestamp

    # -------------------------------------------------------------------------
    # ESCALATION
    # -------------------------------------------------------------------------

    def _escalate(self, topic: str, reason: str):
        label = TOPIC_LABEL.get(topic, topic)
        print(f"[ERROR] [{label}] {reason}")
        # TODO: publish to an alert topic if needed

    # -------------------------------------------------------------------------
    # START / STOP
    # -------------------------------------------------------------------------

    def start(self):
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[Pipeline] Stopped")


# =============================================================================
# TESTS — run with: python pipeline_with_fallback.py
# Tests core logic without needing a broker or simulator.
# =============================================================================

def test_pipeline():
    print("\n" + "=" * 60)
    print("  PIPELINE TESTS")
    print("=" * 60)

    fallback = WeatherFallback(latitude=None, longitude=None)
    pipeline = EnvironmentPipeline(
        broker="", port=0,
        weather_fallback=fallback,
        window_seconds=60,
        connect=False,
    )

    # TEST 1: Rolling average
    print("\n--- TEST 1: Rolling average ---")
    for val in [20.0, 22.0, 24.0]:
        pipeline._record_good_value("temperature_c", val)
    avg          = pipeline.get_average("temperature_c")
    expected_avg = (20.0 + 22.0 + 24.0) / 3
    print(f"  Average: {avg:.4f}, Expected: {expected_avg:.4f}")
    print(f"  PASS: {abs(avg - expected_avg) < 0.001}")

    # TEST 2: latest_values holds the exact last reading (not the average)
    print("\n--- TEST 2: latest_values holds exact last reading ---")
    last_raw   = pipeline.last_known_fallback.get_last_value("temperature_c")
    latest_val = pipeline.latest_values.get("temperature_c")
    avg_val    = pipeline.get_average("temperature_c")
    print(f"  last_raw={last_raw}, latest={latest_val}, average={avg_val:.4f}")
    print(f"  PASS: {last_raw == 24.0 and latest_val == 24.0 and abs(avg_val - 22.0) < 0.001}")

    # TEST 3: Bad status triggers fallback → escalation
    print("\n--- TEST 3: Bad status escalates ---")
    before = pipeline.latest_values.get("humidity_rel")
    pipeline._run_fallback_chain(
        topic="cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature",
        field_name="humidity_rel",
        value=75.0,
        status="sensor_error",
        valid_range=(0.0, 100.0),
    )
    after = pipeline.latest_values.get("humidity_rel")
    print(f"  PASS (unchanged, fallback also failed): {before == after}")

    # TEST 4: P07 location dict updates WeatherFallback coordinates
    print("\n--- TEST 4: P07 location updates WeatherFallback ---")
    pipeline._validate_object(
        topic="cps/p07/DDATA/weather-pipeline",
        field_name="location",
        value={"name": "berlin", "latitude": 52.52, "longitude": 13.405},
    )
    print(f"  lat={fallback.latitude}, lng={fallback.longitude}")
    print(f"  PASS: {fallback.latitude == 52.52 and fallback.longitude == 13.405}")

    # TEST 5: Consecutive miss counter increments correctly
    print("\n--- TEST 5: Consecutive misses ---")
    pipeline._record_good_value("calibrated", 0.55)
    for _ in range(7):
        pipeline._run_fallback_chain(
            topic="cps/p01/DDATA/sensor-main/soil_moisture",
            field_name="calibrated",
            value=None,
            status="sensor_disconnected",
            valid_range=(0.0, 1.0),
        )
    misses = pipeline.consecutive_misses.get("calibrated", 0)
    print(f"  Misses: {misses}, PASS: {misses == 7}")

    # TEST 6: get_data() returns a safe copy — mutating it does not affect the pipeline
    print("\n--- TEST 6: get_data() is a copy ---")
    snapshot = pipeline.get_data()
    snapshot["temperature_c"] = 9999
    actual = pipeline.latest_values.get("temperature_c")
    print(f"  PASS: {actual != 9999}")

    print("\n" + "=" * 60)
    print("  TESTS COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    test_pipeline()
