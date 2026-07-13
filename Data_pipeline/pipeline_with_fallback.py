import csv
import json
import os
import time
import threading
import requests
import paho.mqtt.client as mqtt


# =============================================================================
# SCHEMAS
# Each schema maps one MQTT topic to the fields that topic carries.
# Each field has a "type" that tells _process_field how to validate it:
#   "range"  -> numeric, checked against (min, max)
#   "enum"   -> string, must be one of valid_values
#   "string" -> freeform text, just checked to be a str
#   "object" -> nested dict (e.g. location, staleness from P07)
#   "array"  -> list of items (e.g. forecast_hours from P07)
# =============================================================================

# P03: one combined topic as of 2025-06 (was three separate topics before).
# humidity_rel was previously called humidity_pct.
# light_lux max corrected to 65535 (BH1750 hardware limit).
# sensor_error replaces sensor_disconnected in their status enum.

ENVIRONMENT_SCHEMA = { #P3
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


SOIL_MOISTURE_SCHEMA = { #P1
    "cps/p01/DDATA/sensor-main/soil_moisture": {
        "timestamp":  {"type": "string"},
        "calibrated": {"type": "range", "valid_range": (0.0, 1.0)},
        "raw_adc":    {"type": "range", "valid_range": (0, 65536)},
        "status":     {"type": "enum",
                       "valid_values": ["ok", "sensor_disconnected", "out_of_range"]},
    },
}


# P07: location and staleness are real nested dicts; forecast_hours and
# daily_et_summary are real lists. No second json.loads() needed.
# Always check status first -- if "unavailable", arrays are empty.
WEATHER_API_SCHEMA = { #P7
    "cps/p07/DDATA/weather-pipeline": {
        "weather/data_source":      {"type": "enum",   "valid_values": ["open-meteo"]},
        "weather/location":         {"type": "object"},
        "weather/forecast_hours":   {"type": "array"},
        "weather/daily_et_summary": {"type": "array"},
        "weather/staleness":        {"type": "object"},
        "weather/status":           {"type": "enum",
                                     "valid_values": ["live", "cached", "unavailable"]},
        "weather/message":          {"type": "string"},
        # P07 will publish wind_speed on the same topic once they configure it.
        # Field added here so the pipeline accepts and validates it when it arrives.
        "wind_speed":               {"type": "range", "valid_range": (0.0, 150.0)},
    },
}

SCHEMA = {
    **ENVIRONMENT_SCHEMA,
    **SOIL_MOISTURE_SCHEMA,
    **WEATHER_API_SCHEMA,
}

# Short readable label for each topic, used in terminal output.
TOPIC_LABEL = {
    "cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature": "P03",
    "cps/p03/DDATA/sensor-main/ambient-light":                     "P03",
    "cps/p01/DDATA/sensor-main/soil_moisture":                     "P01",
    "cps/p07/DDATA/weather-pipeline":                              "P07",
}

# Status values from P01/P03/P07 that mean "do not trust this reading".
# P07 uses different vocabulary (live/cached/unavailable), handled separately.
BAD_STATUSES = {"sensor_disconnected", "sensor_error", "out_of_range", "stale", "unavailable"}

# Maximum hours of sensor history to keep in the CSV log.
# When this limit is exceeded, the old file is deleted and a new one starts.
MAX_LOG_HOURS = 8

# Path to the CSV log file — same folder as this script.
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_log.csv")


# =============================================================================
# CLASS: WeatherFallback
# Plan B for temperature_c and humidity_rel when P03 cannot be trusted.
# Calls OpenMeteo using coordinates provided by P07 at runtime.
# lat/lng start as None and are updated when the first P07 message arrives.
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
            response.raise_for_status() #raise_for_status() method is part of the Requests library and is used to check if an HTTP request was successful
            return response.json()["current"]["temperature_2m"] #It converts the HTTP response content into a Python dictionary (or list).
            """
            The expression response.json()["current"]["temperature_2m"] extracts a value from a nested JSON response returned by an API. First, response.json() 
            converts the HTTP response into a Python dictionary. Then ["current"] accesses the nested dictionary under the key "current", and ["temperature_2m"] 
            extracts the actual temperature value from that dictionary. The final result is a single value (usually a float), which is returned by the function.
            """
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
        # OpenMeteo only provides wind speed at 10 m height — the standard
        # meteorological measurement height. We need 2 m (balcony level), so
        # we convert using the Wind Power Law:
        #
        #   v(z) = v(z_ref) × (z / z_ref) ^ α
        #
        # where:
        #   v(z)     = wind speed at our target height (2 m)
        #   v(z_ref) = wind speed at the reference height (10 m) from OpenMeteo
        #   z        = target height in metres = 2
        #   z_ref    = reference height in metres = 10
        #   α        = wind shear exponent — depends on terrain roughness:
        #                0.14  open flat land (fields, sea)
        #                0.25  suburban / urban (our case: Berlin balcony)
        #                0.40  dense city centre with tall buildings
        #
        # For a Berlin balcony α = 0.25 is a reasonable estimate.
        # (2 / 10) ^ 0.25 = 0.2 ^ 0.25 ≈ 0.669
        # So 2 m wind speed is roughly 67 % of the 10 m reading.
        #
        # NOTE: this is still an approximation. A balcony is shielded by the
        # building behind it and affected by neighbours — no formula captures
        # that geometry. Treat this as a rough estimate until P07's anemometer
        # provides the real 2 m value.
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            params = {"latitude": self.latitude, "longitude": self.longitude,
                      "current": "wind_speed_10m"}
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            wind_10m = response.json()["current"]["wind_speed_10m"]  # km/h at 10 m
            alpha    = 0.25          # wind shear exponent for suburban/urban terrain
            wind_2m  = wind_10m * (2 / 10) ** alpha  # power law downscale to 2 m
            return round(wind_2m, 1)
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo wind_speed failed: {e}")
            return None

    def get_light_lux(self):
        # OpenMeteo provides shortwave solar radiation in W/m².
        # Conversion: 1 W/m² ≈ 120 lux for natural daylight.
        # This is an approximation — lux is photometric, radiation is radiometric.
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
            return min(lux, 65535.0)  # clamp to BH1750 sensor max
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo light_lux failed: {e}")
            return None

    def get_soil_moisture(self):
        # OpenMeteo hourly soil moisture (0–1 cm depth) in m³/m³.
        # Typical range: 0.05 (dry) to 0.45 (saturated) — NOT the same unit as
        # calibrated (0.0–1.0), but fits inside the valid range and is a reasonable
        # approximation when the P01 sensor has been down for more than 5 readings.
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
            # Find the value for the current UTC hour.
            current_hour = time.strftime("%Y-%m-%dT%H:00", time.gmtime())
            idx = hourly["time"].index(current_hour)
            return round(hourly["soil_moisture_0_to_1cm"][idx], 3)
        except (requests.RequestException, KeyError, ValueError, IndexError) as e:
            print(f"[Fallback] OpenMeteo soil_moisture failed: {e}")
            return None

# =============================================================================
# CLASS: LastKnownValueFallback
# Plan B for fields where a short gap is tolerable (e.g. soil moisture).
# Reads from last_raw_values -- the exact last trusted reading, never averaged.
# =============================================================================
class LastKnownValueFallback:
    def __init__(self, cache: dict):
        self.cache = cache  # same dict object as pipeline.last_raw_values

    def get_last_value(self, field_name: str):
        return self.cache.get(field_name)


# =============================================================================
# CLASS: EnvironmentPipeline
# Subscribes to every topic in SCHEMA, validates each field, and runs the
# Plan A -> B -> C fallback chain for numeric fields.
# =============================================================================
class EnvironmentPipeline:

    FIELD_FALLBACK_STRATEGY = {
        "temperature_c":  "weather",
        "humidity_rel":   "weather",
        "pressure_hpa":   "weather",
        "wind_speed":     "weather",     # OpenMeteo wind_speed_10m (km/h)
        "light_lux":      "weather",     # OpenMeteo shortwave_radiation × 120 → lux
        "calibrated":     "last_known",  # last known for ≤5 misses, then OpenMeteo soil moisture
        "raw_adc":        "no_fallback", # ADC is hardware-specific, no external source
    }

    def __init__(self, broker: str, port: int, weather_fallback: WeatherFallback,
                 window_seconds: float = 300, connect: bool = True, on_new_reading=None, interval_seconds : int = 30):
        self.weather_fallback  = weather_fallback
        self.window_seconds    = window_seconds
        self.on_new_reading    = on_new_reading #stores the callback function the user passes in. If they don't pass one, it stays None and we simply never call it.

        self.interval_seconds  = interval_seconds #stores how often the heartbeat should fire. Default is 30 seconds.
        
        self._heartbeat_timer  = None #will hold the timer object once the heartbeat starts. We set it to None for now because the timer hasn't started yet.

        self.value_buffer    = {}  # field -> [(timestamp, value), ...]
        self.last_raw_values = {}  # field -> exact last trusted reading
        self.latest_values   = {}  # field -> rolling average or latest value

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

    def _on_connect(self, client, userdata, flags, reason_code, properties): # rc is reason code.
        if not reason_code.is_failure:
            print("[Pipeline] Connected.")
            for topic in SCHEMA:
                client.subscribe(topic)
                print(f"[Pipeline] Subscribed: {topic}")
        else:
            print(f"[Pipeline] Connection failed: {reason_code}")

    def _on_message(self, client, userdata, message):
        topic = message.topic # "spBv1.0/P01/DDATA/sensor-main/soil_moisture"
        #topic is only ONE group's topic. Not all three. paho gives you one message at a time.
        """
        paho creates a MQTTMessage object for every incoming message. It has two attributes you care about: message.topic — a string, 
        e.g. "spBv1.0/P01/DDATA/sensor-main/soil_moisture" message.payload — the raw bytes of the message content, e.g. 
        b'{"calibrated": 0.55}' So topic = message.topic just pulls that string out into a shorter variable name for convenience.
        """
        field_definitions = SCHEMA.get(topic) #SCHEMA.get(topic) uses the topic string as a key and pulls out only One groups main value
        # finds your SOIL_MOISTURE_SCHEMA entry:
        # {"timestamp": ..., "calibrated": ..., "raw_adc": ..., "status": ...}
        if field_definitions is None:
            print(f"[Pipeline] Unknown topic: {topic}")
            return

            # field_definitions = your rulebook from SCHEMA (what values SHOULD look like)
            # data              = P03/P07's real message received over MQTT (actual values)
            #
            # For field_name = "temperature_c":
            #   rules = {"type": "range", "valid_range": (-40.0, 85.0)}  <- your rule
            #   value = 21.5                                              <- P03's real reading
            #
            # _process_field checks: does the real value obey the rule?

        try:
            data = json.loads(message.payload.decode())
            """
            data is now P01's real values
            python{
            "timestamp":     "2026-06-26T14:00:00Z",
            "calibrated":    0.53,
            "raw_adc":       4000,
            "status":        "ok"
            }
            """
            # .decode()    → '{"calibrated": 0.55, "status": "ok"}'   (string)
            # json.loads() → {"calibrated": 0.55, "status": "ok"}     (Python dict)
        except json.JSONDecodeError:
            self._escalate(topic, "malformed JSON payload") #Escalate is the method at the very bottom that immediately takes Fallback C
            return
        
        # P07 uses status to signal data freshness, not sensor health.
        # If unavailable, arrays are empty, nothing useful to process.

        if topic == "cps/p07/DDATA/weather-pipeline":
            for nested_field in ["weather/location", "weather/staleness", "weather/forecast_hours", "weather/daily_et_summary"]: #For nested_field = "weather/location", this gives us: raw = '{"name": "berlin", "latitude": 52.52, "longitude": 13.405}'
                raw = data.get(nested_field)
                if isinstance(raw, str): #json.dumps() is the opposite of json.loads(). It takes a Python dict and turns it into a string. So weather/location inside the payload is not the dict itself — it is a text representation of the dict, wrapped in quotes.
                    try:
                        data[nested_field] = json.loads(raw)
                    except json.JSONDecodeError:
                        self._escalate(topic, f"{nested_field} contained invalid JSON string")
                        return

                # P07 sends "message" only when status is "unavailable", explaining why
                # (e.g. "Cache too old: 26.3 hours"). The '(no reason)' default is a safety
                # net so our escalation log is never blank if the key is missing.
                

        # P07 uses "weather/status" instead of "status" — extract accordingly.
        if topic == "cps/p07/DDATA/weather-pipeline":
            status = data.get("weather/status")
        else:
            status = data.get("status")

        for field_name, rules in field_definitions.items(): # For Calibrated, "type": "range", "valid_range": (0.0, 1.0) in "calibrated": {"type": "range", "valid_range": (0.0, 1.0)""
            if field_name == "status" and topic != "cps/p07/DDATA/weather-pipeline":
                continue
            value = data.get(field_name) # 0.53 = data.get(Calibrated)
            self._process_field(topic, field_name, value, status, rules) #(topic= spBv1.0/P01/DDATA/sensor-main/soil_moisture, field name= Calibrated, value= 0.53, status = ok, rules = {"type": "range", "valid_range": (0.0, 1.0)} )

        # Print one clean summary line per message (Option 1).
        # Only numeric range fields are shown -- strings, objects, arrays are skipped
        # to keep the line short. Warnings and errors print separately above.
        label        = TOPIC_LABEL.get(topic, topic)
        numeric_fields = {
            fn: data.get(fn)
            for fn, rules in field_definitions.items()
            if rules["type"] == "range" and data.get(fn) is not None
        }
        if numeric_fields:
            summary = "  ".join(f"{k}={v}" for k, v in numeric_fields.items())
            print(f"[{label}] status={status}  {summary}")

        if self.on_new_reading is not None:
            self.on_new_reading(self.get_data(), status)

    # -------------------------------------------------------------------------
    # FIELD ROUTING
    # -------------------------------------------------------------------------

    def _process_field(self, topic, field_name, value, status, rules): #(topic= spBv1.0/P01/DDATA/sensor-main/soil_moisture, field name= Calibrated, value= 0.53, status = ok, rules = {"type": "range", "valid_range": (0.0, 1.0)} )
        field_type = rules["type"]  # rules = {"type": "range", "valid_range": (0.0, 1.0)} → field_type = "range"

        if field_type == "range":
            self._run_fallback_chain(topic, field_name, value, status, rules["valid_range"])  #(topic= spBv1.0/P01/DDATA/sensor-main/soil_moisture, field name= Calibrated, value= 0.53, status = ok,  rules["valid_range"] = (0.0, 1.0)} )
        elif field_type == "enum":
            self._validate_enum(topic, field_name, value, rules["valid_values"])  # rules["valid_values"] = ["ok", "sensor_disconnected", "out_of_range"]
        elif field_type == "string":
            self._validate_string(topic, field_name, value)  # value = "2026-06-26T14:00:00Z"
        elif field_type == "object":
            self._validate_object(topic, field_name, value)  # value = {"name": "berlin", "latitude": 52.52, "longitude": 13.405}
        elif field_type == "array":
            self._validate_array(topic, field_name, value)  # value = [{"time": "...", "temperature_c": 21.5, ...}, ...]
        else:
            print(f"[Pipeline] Unknown field type '{field_type}' for {field_name}")


    # -------------------------------------------------------------------------
    # VALIDATION METHODS
    # -------------------------------------------------------------------------

    def _validate_enum(self, topic, field_name, value, valid_values): #(topic= spBv1.0/P01/DDATA/sensor-main/soil_moisture, field name= status, value= 0.53, status = ok,  rules["valid_range"] = (0.0, 1.0)} )
        if value in valid_values:  # "ok" in ["ok", "sensor_disconnected", "out_of_range"] → True
            self.latest_values[field_name] = value  # latest_values["status"] = "ok"
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

        # location carries GPS coordinates that WeatherFallback needs.
        # Update on every P07 message so coords stay current.
        if field_name == "location":
            lat = value.get("latitude")   # value = {"name": "berlin", "latitude": 52.52, "longitude": 13.405} → lat = 52.52
            lng = value.get("longitude")  # lng = 13.405
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
    # PLAN A / B / C FALLBACK CHAIN
    # -------------------------------------------------------------------------

    def _run_fallback_chain(self, topic, field_name, value, status, valid_range):   #(topic= spBv1.0/P01/DDATA/sensor-main/soil_moisture, field name= Calibrated, value= 0.53, status = ok, valid_range = (0.0, 1.0)} )
        # Plan A: trust the sensor if status is clean and value is in range.
        in_range  = True
        if valid_range is not None and value is not None: #True
            in_range = valid_range[0] <= value <= valid_range[1]  # (0.0) <= 0.53 <= (1.0) → True

        status_ok = (status is None) or (status not in BAD_STATUSES) # "ok" not in BAD_STATUSES → True

        if status_ok and value is not None and in_range: # if True and True is True and True:
            self._record_good_value(field_name, value)  # stores exact value in latest_values, last_raw_values, and rolling buffer
            self.consecutive_misses[field_name] = 0
            return

        # Plan B: use the assigned fallback strategy.
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
                print(f"[WARNING] {field_name}: sensor status='{status}', miss #{miss_count}/{self.MAX_TOLERATED_MISSES}, using last known = {fallback_value}")
            else:
                print(f"[WARNING] {field_name}: {miss_count} consecutive misses, exceeded limit.")
                # Secondary fallback for soil moisture: try OpenMeteo after last_known runs out.
                if field_name == "calibrated":
                    fallback_value = self.weather_fallback.get_soil_moisture()
                    if fallback_value is not None:
                        print(f"[WARNING] {field_name}: using OpenMeteo soil moisture as secondary fallback = {fallback_value}")

        if fallback_value is not None:
            self._record_good_value(field_name, fallback_value)
            return

        # Plan C: nothing worked.
        self._escalate(topic, f"{field_name} unavailable from sensor and all fallbacks")

    # -------------------------------------------------------------------------
    # ROLLING BUFFER
    # -------------------------------------------------------------------------

    def _record_good_value(self, field_name: str, value: float): # _record_good_value(Calibrated, o.53)
        now = time.time() #time.time() gives the current time as a big float — seconds since January 1, 1970. Example: 1234567890.0. 

        self.last_raw_values[field_name] = value  # last_raw_values["calibrated"] = 0.53  (exact reading, never averaged)
        self.latest_values[field_name]   = value  # latest_values["calibrated"] = 0.53  (exact latest reading, not an average)

        # Log this trusted reading to the CSV file for 8-hour history.
        self._log_to_csv(field_name, value, now)

        # Keep the rolling buffer for get_average() -- used internally by the fallback chain.
        # setdefault: if "calibrated" key doesn't exist yet, create it with an empty list first.
        self.value_buffer.setdefault(field_name, []).append((now, value))  # value_buffer["calibrated"] = [(1234567890.0, 0.53), ...]

        cutoff = now - self.window_seconds  # e.g. 1234567890.0 - 300 = 1234567590.0  (5 minutes ago)

        # Keep only readings from the last N minutes (window_seconds), discard older ones.
        fresh_readings = []
        for (t, v) in self.value_buffer[field_name]:
            if t >= cutoff:
                fresh_readings.append((t, v))
        self.value_buffer[field_name] = fresh_readings

    # -------------------------------------------------------------------------
    # CSV LOGGING
    # -------------------------------------------------------------------------

    def _log_to_csv(self, field_name: str, value: float, timestamp: float):
        # If the file exists and its first row is older than MAX_LOG_HOURS, delete it.
        # This starts a fresh 8-hour collection cycle.
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip the header row
                first_row = next(reader, None)  # get the first data row
            if first_row is not None:
                first_timestamp = float(first_row[0])
                hours_stored = (timestamp - first_timestamp) / 3600
                if hours_stored >= MAX_LOG_HOURS:
                    os.remove(LOG_FILE)  # delete old file, start fresh
                    print(f"[Log] 8-hour limit reached. Old log deleted, starting fresh.")

        # If file doesn't exist yet, write the header row first.
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
        if field_name not in self.value_buffer:
            return None
        now    = time.time()
        cutoff = now - self.window_seconds
        recent = [v for (t, v) in self.value_buffer[field_name] if t >= cutoff]
        return sum(recent) / len(recent) if recent else None

    def get_data(self, field_name: str = None):
        if field_name is not None:
            return self.latest_values.get(field_name)
        return dict(self.latest_values)

    # -------------------------------------------------------------------------
    # ESCALATION
    # -------------------------------------------------------------------------

    def _escalate(self, topic: str, reason: str):
        label = TOPIC_LABEL.get(topic, topic)
        print(f"[ERROR] [{label}] {reason}")
        ### fill in: publish to an alert topic if needed

    # -------------------------------------------------------------------------
    # START
    # -------------------------------------------------------------------------
    def _schedule_heartbeat(self):
        self._heartbeat_timer = threading.Timer(self.interval_seconds, self._heartbeat_trick)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _heartbeat_trick(self):
        if self.on_new_reading is not None:
            # Heartbeat has no incoming message, so status is None.
            self.on_new_reading(self.get_data(), None)
        self._schedule_heartbeat()

    
    def start(self):
        self.client.loop_start()
        self._schedule_heartbeat()

    def stop(self):
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()
        self.client.loop_stop()
        self.client.disconnect()
        print("[Pipeline] Stopped")


# =============================================================================
# TESTS -- run with: python pipeline_with_fallback.py
# Tests the core logic without needing a broker or simulator.
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

    # TEST 2: latest_values and last_raw_values both hold the exact last reading (not average)
    print("\n--- TEST 2: latest_values holds exact last reading ---")
    last_raw    = pipeline.last_known_fallback.get_last_value("temperature_c")
    latest_val  = pipeline.latest_values.get("temperature_c")
    avg_val     = pipeline.get_average("temperature_c")
    print(f"  last_raw={last_raw}, latest={latest_val}, average={avg_val:.4f}")
    print(f"  PASS: {last_raw == 24.0 and latest_val == 24.0 and abs(avg_val - 22.0) < 0.001}")

    # TEST 3: Bad status triggers fallback -> escalation
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

    # TEST 4: P07 location dict updates WeatherFallback
    print("\n--- TEST 4: P07 location updates WeatherFallback ---")
    pipeline._validate_object(
        topic="cps/p07/DDATA/weather-pipeline",
        field_name="location",
        value={"name": "berlin", "latitude": 52.52, "longitude": 13.405},
    )
    print(f"  lat={fallback.latitude}, lng={fallback.longitude}")
    print(f"  PASS: {fallback.latitude == 52.52 and fallback.longitude == 13.405}")

    # TEST 5: Consecutive miss counter
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

    # TEST 6: get_data() returns a safe copy
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
