import json
import time
import requests
import paho.mqtt.client as mqtt

# =============================================================================
# WHAT THIS FILE IS FOR
# This is your learning copy of pipeline_with_fallback.py.
# The code is identical to the original. The difference is that every
# non-obvious line has a comment explaining:
#   - LOGIC: why this decision was made in the pipeline design
#   - PYTHON: what this Python syntax actually does
# Read top to bottom. When you understand a section, move on.
# =============================================================================


# =============================================================================
# SCHEMAS
# =============================================================================
#
# LOGIC: A schema is a contract. It says "if you publish on this topic,
# your message must have these fields, with these types and these ranges."
# The pipeline uses the schema to know what to expect from each group.
#
# PYTHON: Each schema is a nested dictionary -- a dict whose values are
# themselves dicts. You access nested values by chaining keys:
#   ENVIRONMENT_SCHEMA["spBv1.0/cps/DDATA/p03-node/env_main"]["temperature_c"]["valid_range"]
#   -> (-40.0, 85.0)
#
# Field types the pipeline understands:
#   "range"  -> number, validated against (min, max)
#   "enum"   -> string, must be one of a fixed list
#   "string" -> any text, just checked to be a str
#   "object" -> a nested dict inside the payload (e.g. P07's location)
#   "array"  -> a list inside the payload (e.g. P07's forecast_hours)
# =============================================================================

# LOGIC: P03 updated their spec in 2025-06.
#   - They merged three separate topics into one combined topic.
#   - "humidity_pct" was renamed to "humidity_rel".
#   - They added pressure and fixed the light sensor's max value.
#   - "sensor_disconnected" was renamed to "sensor_error" in their status.
ENVIRONMENT_SCHEMA = {
    "spBv1.0/cps/DDATA/p03-node/env_main": {
        "timestamp":     {"type": "string"},
        "temperature_c": {"type": "range", "valid_range": (-40.0, 85.0)},
        "humidity_rel":  {"type": "range", "valid_range": (0.0, 100.0)},
        "pressure_hpa":  {"type": "range", "valid_range": (300.0, 1100.0)},
        "light_lux":     {"type": "range", "valid_range": (0.0, 65535.0)},
        # PYTHON: valid_values is a list of strings. The pipeline checks:
        # "is the incoming status string inside this list?"
        "status":        {"type": "enum",
                          "valid_values": ["ok", "sensor_error", "out_of_range", "stale"]},
    },
}

# LOGIC: P01 now uses uppercase "P01" in their topic (was lowercase before).
# They added a raw_adc field -- the unprocessed hardware reading kept for
# drift detection. calibrated is the useful number; raw_adc is the evidence.
SOIL_MOISTURE_SCHEMA = {
    "spBv1.0/P01/DDATA/sensor-main/soil_moisture": {
        "timestamp":  {"type": "string"},
        "calibrated": {"type": "range", "valid_range": (0.0, 1.0)},
        # PYTHON: (0, 65536) is a tuple -- like a list but immutable (can't be changed).
        # We use tuples for ranges because the range should never be modified at runtime.
        "raw_adc":    {"type": "range", "valid_range": (0, 65536)},
        "status":     {"type": "enum",
                       "valid_values": ["ok", "sensor_disconnected", "out_of_range"]},
    },
}

PUMP_SCHEMA = {
    "spBv1.0/p02/DDATA/actuator-main/pump": {
        # LOGIC: valid_range is None because P02's documentation gives no numeric bounds.
        # None means "accept any number" -- we skip the range check entirely for these.
        "running_time": {"type": "range", "valid_range": None},
        "volume_l":     {"type": "range", "valid_range": None},
        # LOGIC: This "status" is the pump's operational state (running/idle/error).
        # It is NOT the same concept as a sensor trust signal. The pump's status
        # tells you what it is doing, not whether its data is reliable.
        "status":       {"type": "enum", "valid_values": ["running", "idle", "error"]},
    },
}

# LOGIC: P07 publishes a full weather forecast every 2 hours. Their payload is
# richer than sensors -- it contains nested dicts and lists inside the JSON.
# When json.loads() parses the MQTT payload, "location" becomes a Python dict,
# "forecast_hours" becomes a Python list, etc. -- no extra parsing needed.
# Always check "status" first. If "unavailable", the arrays are empty and
# must not be used. Consuming empty arrays as "no rain expected" would be wrong.
WEATHER_API_SCHEMA = {
    "spBv1.0/P07/NDATA/weather-pipeline": {
        "generated_at":     {"type": "string"},
        # LOGIC: data_source is an enum, not a freeform string, because only
        # one provider is used. Enforcing this catches misconfiguration early.
        "data_source":      {"type": "enum", "valid_values": ["open-meteo"]},
        # LOGIC: location is type "object" (a dict) because P07 sends the
        # coordinates as nested keys, not a plain string. The pipeline reads
        # latitude and longitude from this to update WeatherFallback.
        "location":         {"type": "object"},
        "forecast_hours":   {"type": "array"},   # up to 48 hourly dicts
        "daily_et_summary": {"type": "array"},   # one dict per day
        "staleness":        {"type": "object"},  # freshness metadata
        "status":           {"type": "enum", "valid_values": ["live", "cached", "unavailable"]},
        "message":          {"type": "string"},  # only present when status=unavailable
    },
}

# PYTHON: ** unpacks a dict's key-value pairs into the surrounding dict literal.
# Writing {ENVIRONMENT_SCHEMA, SOIL_MOISTURE_SCHEMA} would crash because dicts
# cannot be put inside a set (sets require hashable items, dicts are not hashable).
# ** is the correct way to merge dicts into one.
SCHEMA = {
    **ENVIRONMENT_SCHEMA,
    **SOIL_MOISTURE_SCHEMA,
    **PUMP_SCHEMA,
    **WEATHER_API_SCHEMA,
}

# LOGIC: These are the status strings from sensors that mean "do not trust
# this reading." They are kept in a set (not a list) because checking
# "value in BAD_STATUSES" is faster on a set than on a list.
# PYTHON: A set is written with {}. Unlike a dict, it has no keys -- just values.
# {"a", "b", "c"} is a set. {"a": 1, "b": 2} is a dict.
# P07 uses "live/cached/unavailable" instead and is handled separately.
BAD_STATUSES = {"sensor_disconnected", "sensor_error", "out_of_range", "stale"}


# =============================================================================
# CLASS: WeatherFallback
# =============================================================================
# LOGIC: This class is Plan B for temperature and humidity. If P03's real
# sensor is broken or unreliable, we ask OpenMeteo (a free weather API)
# for the current outdoor temperature and humidity instead.
#
# LOGIC: latitude and longitude are NOT hardcoded here. P07 publishes the
# real GPS coordinates of our sensor location and the pipeline writes them
# here at runtime. This way, if the sensor moves, you update P07's config,
# not this code.
#
# PYTHON: A class is a blueprint for an object. __init__ is the method that
# runs when you create an object from the blueprint:
#   fallback = WeatherFallback(52.52, 13.405)
# After that line, fallback.latitude = 52.52 and fallback.longitude = 13.405.
# "self" always refers to the specific object being used right now.
# =============================================================================
class WeatherFallback:
    def __init__(self, latitude, longitude):
        # PYTHON: self.latitude means "store latitude as an attribute of THIS object."
        # Any method in this class can then read it with self.latitude.
        self.latitude  = latitude
        self.longitude = longitude
        self.url = "https://api.open-meteo.com/v1/forecast"

    def _coords_ready(self):
        # LOGIC: If P07 has not published yet, lat/lng are still None.
        # Calling OpenMeteo with None would send a bad request and fail.
        # This check prevents that.
        # PYTHON: "is not None" checks whether a variable has been assigned a real value.
        return self.latitude is not None and self.longitude is not None

    def get_temperature(self):
        # LOGIC: Returns a float (degrees Celsius), or None if the request fails.
        # Returning None tells the caller "Plan B also failed, move to Plan C."
        if not self._coords_ready():
            print("[Fallback] Coordinates not yet known; skipping OpenMeteo call.")
            return None
        try:
            # PYTHON: params is a dict of query string parameters. requests.get()
            # automatically appends them to the URL as ?latitude=52.52&longitude=13.405...
            params   = {"latitude": self.latitude, "longitude": self.longitude,
                        "current": "temperature_2m"}
            response = requests.get(self.url, params=params, timeout=5)
            # PYTHON: raise_for_status() raises an exception if the HTTP response
            # code is an error (400, 404, 500, etc.). Without this, a failed
            # request would silently return a response we'd try to parse.
            response.raise_for_status()
            # PYTHON: response.json() parses the response body as JSON into a dict.
            # We then chain ["current"]["temperature_2m"] to navigate the nested dict.
            return response.json()["current"]["temperature_2m"]
        except (requests.RequestException, KeyError, ValueError) as e:
            # LOGIC: We catch three types of errors:
            #   RequestException -> network problem (timeout, no internet, etc.)
            #   KeyError         -> response came back but key we expected wasn't there
            #   ValueError       -> response body wasn't valid JSON
            # In all three cases, Plan B failed. We return None to signal Plan C.
            print(f"[Fallback] OpenMeteo temperature failed: {e}")
            return None

    def get_humidity(self):
        # LOGIC: Same pattern as get_temperature(), just a different API parameter.
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


# =============================================================================
# CLASS: LastKnownValueFallback
# =============================================================================
# LOGIC: For fields like soil moisture, a brief gap is normal -- maybe the
# sensor missed one publish cycle. Rather than treating every gap as a failure,
# we reuse the last trusted reading. This is Plan B for "last_known" fields.
#
# LOGIC: This class reads from last_raw_values, NOT from latest_values.
# latest_values holds rolling averages. A fallback should be the exact last
# real measurement, not a smoothed average -- that average might hide the
# problem the fallback is supposed to bridge.
#
# PYTHON: self.cache IS the pipeline's last_raw_values dict -- not a copy.
# In Python, when you assign a dict to another variable, both point to the
# same object in memory. So when the pipeline writes to last_raw_values,
# this class sees the new value immediately without any extra code.
# =============================================================================
class LastKnownValueFallback:
    def __init__(self, cache: dict):
        self.cache = cache

    def get_last_value(self, field_name: str):
        # PYTHON: dict.get(key) returns the value for key if it exists, or None
        # if it doesn't. It never crashes with a KeyError, unlike dict[key].
        # This is important at startup when the cache is empty.
        return self.cache.get(field_name)


# =============================================================================
# CLASS: NoFallback
# =============================================================================
# LOGIC: Some fields have no possible substitute -- e.g. the pump's running
# state. If the pump sensor fails, there is no external source to ask.
# This class makes that decision explicit and visible in the code, rather
# than just letting a variable silently remain None.
# =============================================================================
class NoFallback:
    def get_last_value(self):
        return None


# =============================================================================
# CLASS: EnvironmentPipeline
# =============================================================================
# LOGIC: This is the main class. It:
#   1. Connects to the MQTT broker
#   2. Subscribes to every topic in SCHEMA
#   3. When a message arrives, validates each field against the schema
#   4. For numeric fields, runs Plan A -> B -> C if something is wrong
#
# TWO SEPARATE CACHES -- this is the most important design decision:
#
#   latest_values   -- what other groups should READ. For numeric fields,
#                      this is a rolling AVERAGE of all trusted readings
#                      in the last window_seconds. For string/enum/object/
#                      array fields, it is simply the latest trusted value.
#
#   last_raw_values -- what LastKnownValueFallback reads. Always the EXACT
#                      last sensor reading, never averaged.
#
# Why two? Because "what should I report as the current temperature?" and
# "what was the temperature right before things broke?" are different questions.
# =============================================================================
class EnvironmentPipeline:

    # PYTHON: A class variable (defined directly under the class, not inside
    # a method) is shared by ALL instances of the class. It is accessed as
    # self.FIELD_FALLBACK_STRATEGY or EnvironmentPipeline.FIELD_FALLBACK_STRATEGY.
    #
    # LOGIC: This table maps each numeric field to its Plan B strategy.
    # Adding a new field's behaviour is one line here, not an if/elif chain
    # buried inside the fallback logic. This is called "table-driven design."
    FIELD_FALLBACK_STRATEGY = {
        "temperature_c":  "weather",      # OpenMeteo has a substitute
        "humidity_rel":   "weather",      # OpenMeteo has a substitute
        "pressure_hpa":   "no_fallback",  ### add WeatherFallback.get_pressure() later
        "light_lux":      "no_fallback",  # no online source for balcony lux
        "volume_l":       "last_known",   # short gaps tolerated
        "calibrated":     "last_known",   # short gaps tolerated
        "raw_adc":        "no_fallback",  # raw ADC has no meaningful substitute
        "running_time":   "no_fallback",  ### confirm with P02
        "pump_runtime_s": "no_fallback",  ### confirm with P02/P05
    }

    def __init__(self, broker: str, port: int, weather_fallback: WeatherFallback,
                 window_seconds: float = 300, connect: bool = True):
        # PYTHON: Parameters with = in the signature have default values.
        # window_seconds=300 means "if the caller doesn't pass this argument,
        # use 300." connect=True means "connect by default; pass False in tests."

        self.weather_fallback = weather_fallback
        # LOGIC: window_seconds is X -- the rolling window for averaging.
        # All readings older than this are dropped from the buffer.
        # It is NOT hardcoded; the caller decides what window makes sense.
        self.window_seconds   = window_seconds

        # PYTHON: All three of these start as empty dicts {}.
        # They are INSTANCE variables (created with self.) meaning each
        # EnvironmentPipeline object gets its own copy of these dicts.
        # Methods in this class read/write them using self.value_buffer etc.
        self.value_buffer    = {}  # field -> [(timestamp, value), ...]
        self.last_raw_values = {}  # field -> exact last trusted reading
        self.latest_values   = {}  # field -> rolling average or latest value

        # LOGIC: LastKnownValueFallback receives last_raw_values (NOT latest_values).
        # Both self.last_known_fallback.cache and self.last_raw_values now point
        # to the same dict object in memory -- not a copy. When one is updated,
        # the other sees it immediately.
        self.last_known_fallback  = LastKnownValueFallback(self.last_raw_values)
        self.no_fallback          = NoFallback()
        self.consecutive_misses   = {}  # field -> number of consecutive misses
        self.MAX_TOLERATED_MISSES = 5   # after this many in a row, escalate

        # PYTHON: mqtt.Client() creates the MQTT client object. We then assign
        # our own methods as "callbacks" -- references to functions that the
        # library will call for us when events happen. We never call
        # _on_connect or _on_message ourselves; paho-mqtt calls them.
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        # LOGIC: connect=False lets us create a pipeline object in unit tests
        # without needing a real broker running. The test can then call
        # internal methods directly.
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
        # LOGIC: This is called for every incoming MQTT message.
        # message.topic tells us which topic it arrived on.
        # message.payload is the raw bytes of the message body.
        topic             = message.topic
        field_definitions = SCHEMA.get(topic)
        if field_definitions is None:
            # LOGIC: A message arrived on a topic we don't have in the schema.
            # This should not happen in normal operation.
            print(f"[Pipeline] Unknown topic: {topic}")
            return

        try:
            # PYTHON: message.payload is bytes. .decode() converts bytes to str.
            # json.loads() converts that str into a Python dict.
            data = json.loads(message.payload.decode())
        except json.JSONDecodeError:
            self._escalate(topic, "malformed JSON payload")
            return

        # LOGIC: P07's "status" field means something different from sensor status.
        # For sensors (P01/P03), status = "was the sensor working this cycle?"
        # For P07, status = "did the weather API call succeed?"
        # If P07 says "unavailable", forecast_hours and daily_et_summary are
        # empty arrays. We must not process them -- we escalate and return early.
        if topic == "spBv1.0/P07/NDATA/weather-pipeline":
            if data.get("status") == "unavailable":
                self._escalate(topic, f"P07 unavailable: {data.get('message', '(no reason)')}")
                return

        # LOGIC: For non-P07 topics, read "status" once per message because it
        # applies to the whole payload. One bad status means all fields are suspect.
        status = data.get("status")

        # PYTHON: field_definitions.items() gives (key, value) pairs.
        # field_name is the key (e.g. "temperature_c"),
        # rules is the value (e.g. {"type": "range", "valid_range": (-40, 85)}).
        for field_name, rules in field_definitions.items():
            # LOGIC: We skip the "status" field itself for non-P07 topics.
            # It was already read above as a trust signal -- it is not a
            # "value to validate and store" the same way temperature is.
            if field_name == "status" and topic != "spBv1.0/P07/NDATA/weather-pipeline":
                continue
            value = data.get(field_name)
            self._process_field(topic, field_name, value, status, rules)

    # -------------------------------------------------------------------------
    # FIELD ROUTING
    # -------------------------------------------------------------------------

    def _process_field(self, topic, field_name, value, status, rules):
        # LOGIC: This method is a router. It reads the "type" from the schema
        # and sends the field to the correct validation method.
        # This keeps each validation method focused on one job.
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
        # LOGIC: Enum fields have no fallback. If the pump's status string
        # is invalid, there is nothing else to ask. Straight to Plan C.
        # PYTHON: "value in valid_values" checks if value exists in the list.
        if value in valid_values:
            print(f"[Plan A] {field_name} = '{value}' (enum)")
            # PYTHON: self.latest_values is the shared dict created in __init__.
            # This line adds or updates one entry in that dict.
            # It is exactly the same as: my_dict["temperature_c"] = 22.5
            self.latest_values[field_name] = value
        else:
            self._escalate(topic, f"{field_name}='{value}' not in {valid_values}")

    def _validate_string(self, topic, field_name, value):
        # LOGIC: None means the field was absent from the payload.
        # Some fields are optional (e.g. P07's "message" only appears when
        # status is "unavailable"). Missing optional fields are not errors.
        if value is None:
            return
        # PYTHON: isinstance(value, str) checks whether value is of type str.
        # This is safer than type(value) == str because it also catches subclasses.
        if isinstance(value, str):
            print(f"[Plan A] {field_name} = '{value}' (string)")
            self.latest_values[field_name] = value
        else:
            # PYTHON: type(value).__name__ gives the name of the type as a string,
            # e.g. "int", "float", "dict". Useful for error messages.
            self._escalate(topic, f"{field_name} expected str, got {type(value).__name__}")

    def _validate_object(self, topic, field_name, value):
        # LOGIC: "object" type fields are nested dicts in the payload.
        # After json.loads() they are already Python dicts -- no extra parsing.
        if value is None:
            return
        # PYTHON: isinstance(value, dict) checks if value is a Python dict.
        if not isinstance(value, dict):
            self._escalate(topic, f"{field_name} expected dict, got {type(value).__name__}")
            return

        print(f"[Plan A] {field_name} = (object, {len(value)} keys)")
        self.latest_values[field_name] = value

        # LOGIC: location is the only object field that requires extra action.
        # It carries latitude and longitude that WeatherFallback needs to make
        # accurate OpenMeteo calls. We update WeatherFallback every time P07
        # publishes a new location so coordinates stay current.
        if field_name == "location":
            # PYTHON: value.get("latitude") reads the "latitude" key from the dict.
            # Returns None if the key is missing, instead of crashing.
            lat = value.get("latitude")
            lng = value.get("longitude")
            if lat is not None and lng is not None:
                # PYTHON: We directly set attributes on another object here.
                # self.weather_fallback is the WeatherFallback instance passed
                # into __init__. We update its latitude and longitude attributes.
                self.weather_fallback.latitude  = lat
                self.weather_fallback.longitude = lng
                print(f"[Pipeline] WeatherFallback updated: lat={lat}, lng={lng}")
            else:
                print("[Pipeline] location missing latitude/longitude keys.")

    def _validate_array(self, topic, field_name, value):
        # LOGIC: "array" type fields are lists in the payload.
        # forecast_hours and daily_et_summary are lists of dicts.
        # We store them as-is; deeper item validation is not implemented yet.
        if value is None:
            return
        # PYTHON: isinstance(value, list) checks if value is a Python list.
        if not isinstance(value, list):
            self._escalate(topic, f"{field_name} expected list, got {type(value).__name__}")
            return

        print(f"[Plan A] {field_name} = (array, {len(value)} items)")
        self.latest_values[field_name] = value

    # -------------------------------------------------------------------------
    # PLAN A / B / C FALLBACK CHAIN
    # -------------------------------------------------------------------------

    def _run_fallback_chain(self, topic, field_name, value, status, valid_range):
        # LOGIC: Three-tier decision for numeric fields only:
        #   Plan A -- real sensor value, trusted
        #   Plan B -- substitute (OpenMeteo or last known reading)
        #   Plan C -- escalate, nothing worked

        # ── Plan A ───────────────────────────────────────────────────────────
        # LOGIC: We only trust the value if ALL three conditions are true:
        #   1. status is not in BAD_STATUSES (sensor is healthy)
        #   2. value is not None (sensor sent something)
        #   3. value is inside the valid range (sensor reading makes sense)

        # PYTHON: in_range starts as True. We only change it if there is a
        # range to check AND a value to check against.
        in_range = True
        if valid_range is not None and value is not None:
            # PYTHON: valid_range is a tuple (min, max).
            # valid_range[0] is min, valid_range[1] is max.
            # Python allows chained comparisons: a <= b <= c means a<=b AND b<=c.
            in_range = valid_range[0] <= value <= valid_range[1]

        # LOGIC: status_ok is True when status is None (field not present, not a problem)
        # OR when status is not one of the known bad strings.
        # "not in BAD_STATUSES" reads naturally and avoids a long OR chain.
        status_ok = (status is None) or (status not in BAD_STATUSES)

        if status_ok and value is not None and in_range:
            print(f"[Plan A] {field_name} = {value}")
            self._record_good_value(field_name, value)
            self.consecutive_misses[field_name] = 0
            return  # PYTHON: return with no value exits the method early.

        print(f"[Pipeline] {field_name}: value={value}, status='{status}' -> not trusted.")

        # ── Plan B ───────────────────────────────────────────────────────────
        # PYTHON: dict.get(key, default) returns default if key is not found.
        # "no_fallback" is the safe default for fields not listed in the table.
        strategy       = self.FIELD_FALLBACK_STRATEGY.get(field_name, "no_fallback")
        fallback_value = None

        if strategy == "weather":
            print(f"[Plan B] {field_name}: trying OpenMeteo...")
            if field_name == "temperature_c":
                fallback_value = self.weather_fallback.get_temperature()
            elif field_name == "humidity_rel":
                fallback_value = self.weather_fallback.get_humidity()
            # LOGIC: Weather strategy has no miss counter. OpenMeteo either
            # answers right now or it doesn't. There is no "tolerate a few misses."

        elif strategy == "last_known":
            # LOGIC: Increment the consecutive miss counter for this field.
            # dict.get(field_name, 0) returns 0 if this field has no counter yet.
            self.consecutive_misses[field_name] = (
                self.consecutive_misses.get(field_name, 0) + 1
            )
            miss_count = self.consecutive_misses[field_name]

            if miss_count <= self.MAX_TOLERATED_MISSES:
                # LOGIC: Still within tolerance -- use the last real reading.
                fallback_value = self.last_known_fallback.get_last_value(field_name)
                print(f"[Plan B] {field_name}: miss #{miss_count}, last known = {fallback_value}")
            else:
                # LOGIC: Too many consecutive misses. The sensor is probably
                # broken, not just delayed. Stop pretending the last reading is valid.
                # NOTE: this only catches misses IN A ROW. A pattern of misses
                # spread over time (3 now, pause, 4 later) needs a rolling-window
                # tracker -- not implemented yet.
                print(f"[Plan B] {field_name}: {miss_count} misses, exceeded limit.")

        # LOGIC: "no_fallback" strategy falls through here with fallback_value=None.

        if fallback_value is not None:
            print(f"[Plan B] {field_name} = {fallback_value} (strategy={strategy})")
            # LOGIC: Store the fallback value, but do NOT add it to the rolling
            # buffer or last_raw_values. Those caches hold real sensor readings only.
            self.latest_values[field_name] = fallback_value
            return

        # ── Plan C ───────────────────────────────────────────────────────────
        self._escalate(topic, f"{field_name} unavailable from sensor and all fallbacks")

    # -------------------------------------------------------------------------
    # ROLLING BUFFER
    # -------------------------------------------------------------------------

    def _record_good_value(self, field_name: str, value: float):
        # LOGIC: Called every time Plan A succeeds. Does three things:
        #   1. Stores the exact raw value for LastKnownValueFallback.
        #   2. Adds (timestamp, value) to the rolling buffer.
        #   3. Drops old entries, recomputes the average, stores it in latest_values.

        # PYTHON: time.time() returns the current Unix timestamp -- a float
        # representing seconds since January 1st 1970. It increases by 1.0
        # every real-world second. Used here to know when this value arrived.
        now = time.time()

        # LOGIC: Exact last reading -- what fallback uses. Never averaged.
        self.last_raw_values[field_name] = value

        # PYTHON: setdefault(key, default) creates the key with the default value
        # if the key doesn't exist yet, then returns the value (existing or new).
        # This avoids writing: if field_name not in self.value_buffer: ...
        # .append((now, value)) adds a tuple (timestamp, value) to the list.
        self.value_buffer.setdefault(field_name, []).append((now, value))

        # LOGIC: Drop any entries older than window_seconds.
        # cutoff is the timestamp X seconds ago. Anything before that is too old.
        cutoff = now - self.window_seconds
        # PYTHON: List comprehension -- builds a new list by filtering the old one.
        # "(t, v) for (t, v) in self.value_buffer[field_name] if t >= cutoff"
        # reads as: "keep (t, v) pairs where t is not older than cutoff."
        self.value_buffer[field_name] = [
            (t, v) for (t, v) in self.value_buffer[field_name] if t >= cutoff
        ]

        # PYTHON: Another list comprehension. (_, v) means "unpack the tuple but
        # ignore the first element (timestamp) with _. Keep only v (the value)."
        values_in_window = [v for (_, v) in self.value_buffer[field_name]]
        # LOGIC: Store the rolling average in latest_values. This is what other
        # parts of the system read via get_data() and get_average().
        self.latest_values[field_name] = sum(values_in_window) / len(values_in_window)

    # -------------------------------------------------------------------------
    # PUBLIC ACCESSORS
    # -------------------------------------------------------------------------

    def get_average(self, field_name: str):
        # LOGIC: Returns the rolling average fresh from the buffer.
        # Useful if time has passed since the last message -- some old entries
        # may have aged out of the window since latest_values was last updated.
        if field_name not in self.value_buffer:
            return None
        now    = time.time()
        cutoff = now - self.window_seconds
        recent = [v for (t, v) in self.value_buffer[field_name] if t >= cutoff]
        # PYTHON: "X if condition else Y" is a one-line if/else.
        # Returns sum/len if recent has items, None if the list is empty.
        return sum(recent) / len(recent) if recent else None

    def get_data(self, field_name: str = None):
        # LOGIC: Read-only accessor for other groups or modules.
        # Returns a COPY of latest_values so external code cannot accidentally
        # modify the pipeline's internal state.
        # PYTHON: dict() with a dict argument creates a shallow copy.
        if field_name is not None:
            return self.latest_values.get(field_name)
        return dict(self.latest_values)

    # -------------------------------------------------------------------------
    # ESCALATION
    # -------------------------------------------------------------------------

    def _escalate(self, topic: str, reason: str):
        # LOGIC: Plan C. Nothing more can be done automatically.
        # In a real deployment you would also publish this to an alert MQTT topic
        # so operators know something is broken.
        print(f"[Plan C - ESCALATE] {topic}: {reason}")
        ### fill in: publish to an alert topic if needed

    # -------------------------------------------------------------------------
    # START
    # -------------------------------------------------------------------------

    def start(self):
        # LOGIC: loop_forever() blocks here permanently and processes incoming
        # MQTT messages by calling _on_connect and _on_message automatically.
        # It does not return until the process is killed or crashes.
        # This is why the pipeline uses loop_forever() and the simulator
        # uses loop_start() -- the simulator still needs to run its own
        # while True loop after connecting.
        self.client.loop_forever()


# =============================================================================
# TESTS
# =============================================================================
# LOGIC: These tests check that the pipeline behaves correctly without needing
# a live MQTT broker. connect=False skips the real network connection so we
# can call internal methods directly.
#
# Run with: python pipeline_with_fallback_practice.py
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
    # LOGIC: Feed three values, check that the average is correct.
    print("\n--- TEST 1: Rolling average ---")
    for val in [20.0, 22.0, 24.0]:
        pipeline._record_good_value("temperature_c", val)
    avg          = pipeline.get_average("temperature_c")
    expected_avg = (20.0 + 22.0 + 24.0) / 3
    print(f"  Average: {avg:.4f}, Expected: {expected_avg:.4f}")
    print(f"  PASS: {abs(avg - expected_avg) < 0.001}")

    # TEST 2: last_raw_values holds the EXACT last reading, not the average.
    # LOGIC: After feeding 20, 22, 24 -- last_raw should be 24 (exact last),
    # but latest_values should be 22 (average of all three).
    print("\n--- TEST 2: last_raw vs average ---")
    last_raw = pipeline.last_known_fallback.get_last_value("temperature_c")
    avg_val  = pipeline.latest_values.get("temperature_c")
    print(f"  last_raw={last_raw}, average={avg_val:.4f}, differ={last_raw != avg_val}")
    print(f"  PASS: {last_raw == 24.0 and abs(avg_val - 22.0) < 0.001}")

    # TEST 3: Bad status triggers fallback -> escalation.
    # LOGIC: P03 now uses "sensor_error" (not "sensor_disconnected").
    # With lat/lng=None, WeatherFallback skips OpenMeteo, so Plan C fires.
    print("\n--- TEST 3: Bad status escalates ---")
    before = pipeline.latest_values.get("humidity_rel")
    pipeline._run_fallback_chain(
        topic="spBv1.0/cps/DDATA/p03-node/env_main",
        field_name="humidity_rel",
        value=75.0,
        status="sensor_error",
        valid_range=(0.0, 100.0),
    )
    after = pipeline.latest_values.get("humidity_rel")
    print(f"  PASS (unchanged, fallback also failed): {before == after}")

    # TEST 4: P07 location dict updates WeatherFallback.
    # LOGIC: We pass a real Python dict (not a JSON string) because P07's
    # payload arrives already parsed by json.loads().
    print("\n--- TEST 4: P07 location updates WeatherFallback ---")
    pipeline._validate_object(
        topic="spBv1.0/P07/NDATA/weather-pipeline",
        field_name="location",
        value={"name": "berlin", "latitude": 52.52, "longitude": 13.405},
    )
    print(f"  lat={fallback.latitude}, lng={fallback.longitude}")
    print(f"  PASS: {fallback.latitude == 52.52 and fallback.longitude == 13.405}")

    # TEST 5: Consecutive miss counter.
    # LOGIC: calibrated uses "last_known" strategy. Seed it with 0.55 so
    # there IS a last known value, then send 7 bad messages. After 5,
    # the limit is exceeded and Plan C fires instead of Plan B.
    print("\n--- TEST 5: Consecutive misses ---")
    pipeline._record_good_value("calibrated", 0.55)
    for _ in range(7):
        pipeline._run_fallback_chain(
            topic="spBv1.0/P01/DDATA/sensor-main/soil_moisture",
            field_name="calibrated",
            value=None,
            status="sensor_disconnected",
            valid_range=(0.0, 1.0),
        )
    misses = pipeline.consecutive_misses.get("calibrated", 0)
    print(f"  Misses: {misses}, PASS: {misses == 7}")

    # TEST 6: get_data() returns a copy, not the live dict.
    # LOGIC: If we modify the returned dict, the pipeline's internal
    # latest_values must not change. This protects against accidental edits.
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
