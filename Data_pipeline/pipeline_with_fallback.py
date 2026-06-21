import json
import time
import requests
import paho.mqtt.client as mqtt


"""
The given ENVIRONMENT_SCHEMA is a nested dictionary, meaning that each key maps to another dictionary, and that inner dictionary can itself 
contain further dictionaries. This structure allows organizing complex data hierarchically. In this case, the outer keys are topics, each topic 
maps to a dictionary of variables (like temperature_c), and each variable maps to another dictionary containing properties such as type and valid 
range. To access values, you chain keys step by step: first access the topic, then the variable, then the property. For example,
ENVIRONMENT_SCHEMA["spBv1.0/p03/DDATA/sensor-main/temperature"]["temperature_c"]["valid_range"]
returns the range (-40.0, 85.0).
"""
ENVIRONMENT_SCHEMA = {
    "spBv1.0/p03/DDATA/sensor-main/temperature": {
        "temperature_c": {"type": "range", "valid_range": (-40.0, 85.0)},
    },
    "spBv1.0/p03/DDATA/sensor-main/humidity": {
        "humidity_pct": {"type": "range", "valid_range": (0.0, 100.0)},
    },
    "spBv1.0/p03/DDATA/sensor-main/light": {
        "light_lux": {"type": "range", "valid_range": (0.0, 130000.0)},
    },
}
 
SOIL_MOISTURE_SCHEMA = {
    "spBv1.0/p01/DDATA/sensor-main/soil_moisture": {
        "calibrated": {"type": "range", "valid_range": (0.0, 1.0)},
    },
}
 
PUMP_SCHEMA = {
    "spBv1.0/p02/DDATA/actuator-main/pump": {
        # valid_range is None: source documentation gives no numeric bound.
        "running_time":     {"type": "range", "valid_range": None},
        "volume_l":         {"type": "range", "valid_range": None},
        "status":           {"type": "enum",  "valid_values": ["running", "idle", "error"]},
    },
}
 
WATER_CONTROLLING_SCHEMA = {
    "spBv1.0/p02/DCMD/actuator-main/pump": {
        "type":             {"type": "enum", "valid_values": ["run_for_duration", "stop", "emergency_stop"],},
        "pump_runtime_s":   {"type": "range","valid_range": (1, 120),},
            # NOTE: only required when type == "run_for_duration", ignored
            # otherwise. That conditional logic isn't expressible in this
            # dict -- it would need to live in validation code, not here.
        
    },
    "spBv1.0/p05/NDATA/watering-controller": {
        "state":            {"type": "enum", "valid_values": ["idle", "soaking", "watering", "suppressed", "error"],},
    },
}
 
# Merge all schemas into one lookup table the pipeline reads from.
# ** unpacks each dict's key-value pairs into the new combined dict --
# {dict1, dict2} would try to build a SET and crash, since dicts can't
# be set elements (they're unhashable).
SCHEMA = {
    **ENVIRONMENT_SCHEMA,
    **SOIL_MOISTURE_SCHEMA,
    **PUMP_SCHEMA,
    **WATER_CONTROLLING_SCHEMA,
}
 
# Status values that mean "do not trust this value" -- shared across every
# sensor group's "status" field, since they all use this same vocabulary
# to mean the same thing. P02's "running|idle|error" and P05's "state" are
# a DIFFERENT concept (operational state, not data trust) -- those live in
# each field's own "valid_values" above, not in this set.
BAD_STATUSES = {"sensor_disconnected", "out_of_range", "stale"}
 
 
# ─────────────────────────────────────────────
# CLASS: WeatherFallback
# Plan B for fields that have a real external substitute: calls OpenMeteo
# to get a stand-in value when the real sensor (P03) can't be trusted.
# This class knows nothing about MQTT -- it only knows how to ask OpenMeteo
# for a number. That separation is what lets it be reused or tested on its
# own, independent of the pipeline that calls it.
# ─────────────────────────────────────────────
class WeatherFallback:
    def __init__(self, latitude: float, longitude: float):
        self.latitude = latitude
        self.longitude = longitude
        self.url = "https://api.open-meteo.com/v1/forecast"
 
    def get_temperature(self):
        """Plan B for temperature_c. Returns float or None if this also fails."""
        try:
            params = {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "current": "temperature_2m",
            }
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            return data["current"]["temperature_2m"]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo also failed: {e}")
            return None  # signals: even Plan B failed, go to Plan C (escalate)
 
    def get_humidity(self):
        """Plan B for humidity_pct."""
        try:
            params = {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "current": "relative_humidity_2m",
            }
            response = requests.get(self.url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            return data["current"]["relative_humidity_2m"]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Fallback] OpenMeteo also failed: {e}")
            return None
 
 
# ─────────────────────────────────────────────
# CLASS: LastKnownValueFallback
# Plan B for fields where a brief gap is NOT a hardware fault -- e.g. a
# missed publish interval on volume_l or soil moisture. Reuses the last
# good reading instead of treating every gap as a full failure.
# Reads from a cache it's GIVEN -- it never fetches anything new itself.
# ─────────────────────────────────────────────
class LastKnownValueFallback:
    def __init__(self, cache: dict):
        # Takes the pipeline's OWN latest_values dict rather than keeping a
        # private copy, so there is exactly one place holding "the last good
        # value per field" -- two separate caches could drift out of sync.
        self.cache = cache
 
    def get(self, field_name: str):
        # Returns the last known good value, or None if we've never
        # received a good value for this field yet (e.g. right at startup).
        return self.cache.get(field_name)
 
 
# ─────────────────────────────────────────────
# CLASS: NoFallback
# Documents INTENT for fields with no substitute at all (e.g. the pump's
# running state -- there is nothing else that can tell you if it's running).
# Kept as a real class instead of inlining "return None" so this decision
# is visible and searchable in the code, not a placeholder someone forgot.
# ─────────────────────────────────────────────
class NoFallback:
    def get(self):
        return None
 
 
# ─────────────────────────────────────────────
# CLASS: EnvironmentPipeline
# Responsibility: subscribe to every topic in SCHEMA, validate each
# incoming field against its rules, and for NUMERIC fields only, run the
# tiered fallback chain (Plan A -> Plan B -> Plan C).
#
# IMPORTANT SCOPE NOTE: fallback is applied ONLY to
# numeric ("range") fields. Enum fields (status, type, state) are
# validated against valid_values, but if invalid, they go straight to
# escalate -- there is no Plan B for "the pump's status string is wrong,"
# only for missing/untrustworthy numeric readings.
# ─────────────────────────────────────────────
class EnvironmentPipeline:
    # Maps each numeric field to which fallback strategy applies to it.
    # Adding a new numeric field's behavior is one line here, not a
    # branching if/elif chain inside the logic below.
    FIELD_FALLBACK_STRATEGY = {
        "temperature_c": "weather",
        "humidity_pct": "weather",
        "light_lux": "no_fallback",   # no online equivalent for balcony lux
        "volume_l": "last_known",     # brief gaps tolerated, not a hardware fault
        "calibrated": "last_known",   # same reasoning applies to soil moisture
        "running_time": "no_fallback",  ### fill in: confirm with P02 if a strategy makes sense here
        "pump_runtime_s": "no_fallback",  ### fill in: confirm with P05/P02 if a strategy makes sense here
    }
 
    def __init__(self, broker: str, port: int, weather_fallback: WeatherFallback):
        self.weather_fallback = weather_fallback
        self.latest_values = {}  # holds the most recent good value per field
 
        # Built after self.latest_values exists, since LastKnownValueFallback
        # needs a reference to THIS pipeline's own cache.
        self.last_known_fallback = LastKnownValueFallback(self.latest_values)
        self.no_fallback = NoFallback()
 
        # Counts consecutive misses PER FIELD -- resets to 0 on any success,
        # so a temperature miss streak doesn't affect humidity's count.
        self.consecutive_misses = {}
 
        # Named constant instead of a bare "5" inside the logic below --
        # changing tolerance later means editing one line here.
        self.MAX_TOLERATED_MISSES = 5
 
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(broker, port)
 
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[Pipeline] Connected.")
            for topic in SCHEMA:
                client.subscribe(topic)
                print(f"[Pipeline] Subscribed: {topic}")
        else:
            print(f"[Pipeline] Connection failed, code={rc}")
 
    def _on_message(self, client, userdata, message):
        """
        Entry point for every incoming message, regardless of which schema
        the topic belongs to. SCHEMA now maps each topic to a dict of
        MULTIPLE fields (not just one), so we loop over every field defined
        for this topic and validate/process each one individually.
        """
        topic = message.topic
        field_definitions = SCHEMA.get(topic)
        if field_definitions is None:
            print(f"[Pipeline] Unknown topic: {topic}")
            return
 
        try:
            data = json.loads(message.payload.decode())
        except json.JSONDecodeError:
            print(f"[Pipeline] Malformed payload on {topic}, escalating.")
            self._escalate(topic, "malformed payload")
            return
 
        # status is read once per message (when present) since it applies
        # to the whole payload, the same way P01/P03 use it.
        status = data.get("status")
 
        for field_name, rules in field_definitions.items():
            if field_name == "status":
                continue  # status is the trust signal, not a value to process itself
            value = data.get(field_name)
            self._process_field(topic, field_name, value, status, rules)
 
    def _process_field(self, topic, field_name, value, status, rules):
        """
        Routes a single field to the correct validation path based on its
        "type" tag: enum fields go to plain validation only (no fallback);
        range fields go to the full Plan A/B/C fallback chain.
        """
        if rules["type"] == "enum":
            self._validate_enum(topic, field_name, value, rules["valid_values"])
        elif rules["type"] == "range":
            self._run_fallback_chain(topic, field_name, value, status, rules["valid_range"])
 
    def _validate_enum(self, topic, field_name, value, valid_values):
        """
        Enum fields (status, type, state) have no numeric fallback -- per
        decision, fallback is for numeric data only. An invalid enum
        value goes straight to Plan C, skipping A/B entirely.
        """
        if value in valid_values:
            print(f"[Plan A] {field_name} = {value} (valid)")
            self.latest_values[field_name] = value
        else:
            self._escalate(topic, f"{field_name}='{value}' not in {valid_values}")
 
    def _run_fallback_chain(self, topic, field_name, value, status, valid_range):
        """
        Plan A -> Plan B -> Plan C for NUMERIC fields only, in that order,
        stopping at the first success.
        """
        # ── Plan A: the real sensor value, trusted only if status is "ok"
        # (when status exists) AND the value falls inside its valid_range
        # (when a range is defined -- some fields like running_time have
        # valid_range=None, meaning we skip the range check entirely). ──
        in_range = True
        if valid_range is not None and value is not None:
            in_range = valid_range[0] <= value <= valid_range[1]
 
        status_ok = (status is None) or (status not in BAD_STATUSES)
 
        if status_ok and value is not None and in_range:
            print(f"[Plan A] {field_name} = {value} (status={status})")
            self.latest_values[field_name] = value
            self.consecutive_misses[field_name] = 0
            return
 
        print(f"[Pipeline] {field_name} status='{status}', value={value} -> not trusted.")
 
        # ── Plan B: strategy depends on the field ──
        strategy = self.FIELD_FALLBACK_STRATEGY.get(field_name, "no_fallback")
        fallback_value = None
 
        if strategy == "weather":
            ### fill in: print a message here showing which field is being attempted via OpenMeteo
            if field_name == "temperature_c":
                fallback_value = self.weather_fallback.get_temperature()
            elif field_name == "humidity_pct":
                fallback_value = self.weather_fallback.get_humidity()
            # weather fields don't use the tolerate-then-escalate miss
            # counter -- OpenMeteo either answers right now or it doesn't.
 
        elif strategy == "last_known":
            self.consecutive_misses[field_name] = self.consecutive_misses.get(field_name, 0) + 1
            miss_count = self.consecutive_misses[field_name]
 
            if miss_count <= self.MAX_TOLERATED_MISSES:
                fallback_value = self.last_known_fallback.get(field_name)
                ### fill in: print a message here showing the miss_count and the value used
            else:
                ### fill in: print a message here explaining MAX_TOLERATED_MISSES was exceeded
                pass
                # NOTE: this only catches misses IN A ROW. A repeating
                # pattern of misses spread across separate episodes (3 now,
                # 2 later, 4 even later) needs a different mechanism -- a
                # rolling time-window tracker -- not implemented here yet.
 
        # strategy == "no_fallback" falls through with fallback_value=None
 
        if fallback_value is not None:
            print(f"[Plan B] {field_name} = {fallback_value} (strategy={strategy})")
            self.latest_values[field_name] = fallback_value
            return
 
        # ── Plan C: escalate, nothing worked ──
        self._escalate(topic, f"{field_name} unavailable from sensor and fallback")
 
    def _escalate(self, topic: str, reason: str):
        """Final plan: report to the user/log. No more fallbacks below this."""
        print(f"[Plan C - ESCALATE] Topic '{topic}': {reason}. "
              f"This part of the system is not working.")
        ### fill in: optionally publish this to an alert topic, e.g.
        ### self.client.publish("NDATA/digital-twin-main/alert", json.dumps({...}))

    def start(self):
        self.client.loop_forever()
        # This hands control over to the library. Internally (inside paho-mqtt's own code, which you never see or 
        # write), it's doing something conceptually like this:
        # This is INSIDE the library's source code — not your script
        # while True:
        #     raw_bytes = socket.read()                  # read raw network data
        #     msg = MQTTMessage()                        # library builds the object
        #     msg.topic = extracted_topic_string         # library fills in .topic
        #     msg.payload = extracted_payload_bytes      # library fills in .payload
        #     self.on_message(self, userdata, msg)        # library calls YOUR function, passing the object it built
        # That MQTTMessage() line is the one you were searching for — and it genuinely is not in your script. It lives inside the installed paho-mqtt package on your computer.
        """
        my_obj = SomeClass()
        where you see the object creation with your own eyes. But with callbacks (which is what on_message is), the library creates the 
        object and hands it to you — you only ever receive it as a function parameter, you never type the line that builds it. This is 
        genuinely one of the more confusing ideas in event-driven programming the first time you encounter it, so it's a good thing you 
        pushed on this instead of accepting it at face value.
        """