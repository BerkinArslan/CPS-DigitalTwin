# WATR Data Pipeline — Context for Claude Code

Read this entire file before doing anything. It replaces all previous context.

---

## Who I am

Rohel. Beginner Python programmer. TU Berlin, CPS course, project WATR.
My responsibilities: P07 (Weather API) and P15 (Digital Twin data pipeline).
Group number: Group 15.

Working style:
- Explain WHY, not just what. Line-by-line if needed.
- Ask clarifying questions before large rewrites.
- No unnecessary refactoring. Change only what is needed.
- I like simple code. Avoid clever one-liners.

---

## Repo

GitHub: github.com/BerkinArslan/CPS-DigitalTwin  
Working branch: Data_pipeline_with_fallback_plan

---

## Files in Data_pipeline/

| File | Purpose |
|---|---|
| pipeline_with_fallback.py | MAIN FILE. All classes, schemas, fallback logic, CSV logger. |
| run_pipeline.py | Entry point. Run this to start the pipeline. |
| read_sensor_log.py | Helper to query sensor_log.csv (no MQTT needed). |
| environment_simulator.py | Test publisher. Fakes P01, P03, P07 messages for local testing. |
| p01.py | P01 team's official schema file (soil moisture). |
| p03.py | P03 team's official schema file (environmental sensors). |
| p07.py | P07 team's official schema file (weather API). |
| sensor_log.csv | Auto-generated. 8-hour rolling log of trusted readings. |
| pipeline_with_fallback_practice.py | My learning copy. Ignore for real work. |
| test.py | Scratch file for experiments. Ignore. |
| CPS_Pipeline_v1.0.docx | API reference documentation I wrote. |

---

## What pipeline_with_fallback.py does (fully built and working)

### Classes

**WeatherFallback(latitude, longitude)**
- Calls OpenMeteo API for current temperature, humidity, surface pressure
- Methods: get_temperature(), get_humidity(), get_pressure()
- Used as Plan B when P03 sensor fails

**LastKnownValueFallback(cache)**
- Holds a reference to pipeline.last_raw_values dict
- Method: get_last_value(field_name) — returns last trusted reading

**EnvironmentPipeline(broker, port, weather_fallback, window_seconds, connect)**
- Subscribes to all topics in SCHEMA
- Validates every field on every message
- Runs Plan A -> B -> C fallback chain for numeric fields
- Logs every trusted reading to sensor_log.csv
- Public methods:
  - start() — blocks, runs MQTT loop
  - get_data(field_name=None) — returns latest trusted value(s)
  - get_average(field_name) — rolling average over window_seconds

### Fallback chain

Plan A: sensor value is in valid range AND status not in BAD_STATUSES → store it  
Plan B: use the strategy in FIELD_FALLBACK_STRATEGY:
  - "weather" → call WeatherFallback (temperature_c, humidity_rel, pressure_hpa)
  - "last_known" → use LastKnownValueFallback, max 5 consecutive misses (calibrated)
  - "no_fallback" → skip (light_lux, raw_adc)  
Plan C: print [ERROR], store nothing

### CSV logging (sensor_log.csv)

Every trusted reading (Plan A or B success) is appended.
Columns: timestamp_unix, timestamp_utc, field, value
Resets after 8 hours automatically.

### Terminal output

[P03] status=ok  temperature_c=21.3  humidity_rel=58.1  ...  (one line per message)
[WARNING] field: sensor status='sensor_error', using OpenMeteo fallback = 18.4
[ERROR] [P03] field unavailable from sensor and all fallbacks

---

## THE CURRENT PROBLEM — topics are wrong

My pipeline_with_fallback.py has outdated topic strings taken from an old website.
The correct topics come from the team schema files (p01.py, p03.py, p07.py).

### What my pipeline currently has vs. what it should be

**P01 (soil moisture)**
- My current topic:  spBv1.0/P01/DDATA/sensor-main/soil_moisture
- Correct topic:     cps/p01/DDATA/sensor-main/soil_moisture
- Fields: same (calibrated, raw_adc, status) — no change needed

**P03 (environmental)**
- My current: ONE topic "spBv1.0/cps/DDATA/p03-node/env_main" with all 4 fields
- Correct: TWO separate topics:
  - "cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature" → temperature_c, humidity_rel, pressure_hpa, status
  - "cps/p03/DDATA/sensor-main/ambient-light" → light_lux, status
- This is a structural change — the schema needs to be split

**P07 (weather)**
- My current topic:  spBv1.0/P07/NDATA/weather-pipeline
- Correct topic:     cps/p07/DDATA/weather-pipeline
- Field names also changed — they now all have a "weather/" prefix:
  - "status"             → "weather/status"
  - "location"           → "weather/location"
  - "forecast_hours"     → "weather/forecast_hours"
  - "daily_et_summary"   → "weather/daily_et_summary"
  - "staleness"          → "weather/staleness"
  - "data_source"        → "weather/data_source"
  - "message"            → "weather/message"
- IMPORTANT: their nested fields (location, staleness, forecast_hours,
  daily_et_summary) are JSON-encoded STRINGS inside the payload.
  So after json.loads(message.payload.decode()), those fields are still
  strings — you need a second json.loads() to get the actual dict/list.
  My current code does not handle this.

### Downstream effects of these changes

When P03 splits into two topics, the summary print line in _on_message
still works fine (it loops over field_definitions and prints numeric fields).

The TOPIC_LABEL dict also needs updating to match the new topic strings.

The P07 status check in _on_message currently does:
  if data.get("status") == "unavailable":
This needs to become:
  if data.get("weather/status") == "unavailable":

The environment_simulator.py also publishes on the OLD topics.
Once pipeline topics are fixed, the simulator needs updating too
so local testing still works.

---

## What needs to be changed (in order)

1. In pipeline_with_fallback.py:
   a. Update ENVIRONMENT_SCHEMA: split into two topics for P03
   b. Update SOIL_MOISTURE_SCHEMA: fix P01 topic prefix
   c. Update WEATHER_API_SCHEMA: fix P07 topic + rename all fields with "weather/" prefix
   d. Update TOPIC_LABEL dict to match new topic strings
   e. In _on_message: fix P07 status check (data.get("weather/status"))
   f. In _on_message: add a second json.loads() for P07 nested fields
      (location, staleness, forecast_hours, daily_et_summary)

2. In environment_simulator.py:
   a. Update all three topic strings to match the new correct topics
   b. Update P07 payload field names to use "weather/" prefix
   c. Update P03 to publish on two separate topics instead of one

3. run_pipeline.py: no changes needed unless broker address changed

---

## Design decisions already made — do not re-litigate

- paho-mqtt version is 2.1.0 → use mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
- _on_connect callback must have 5 args: (self, client, userdata, flags, reason_code, properties)
- Use reason_code.is_failure (not rc == 0)
- latest_values stores the exact latest reading, NOT a rolling average
- last_raw_values stores the same (exact latest), used by LastKnownValueFallback
- value_buffer keeps a rolling list for get_average() only
- MAX_TOLERATED_MISSES = 5 (for "last_known" strategy)
- BAD_STATUSES = {"sensor_disconnected", "sensor_error", "out_of_range", "stale"}
- P07 status field uses different vocabulary (live/cached/unavailable) — handled
  separately in _on_message, not via BAD_STATUSES

---

## Memory isolation note (important for understanding)

pipeline_with_fallback.py and any other script are separate Python processes.
They do NOT share memory. get_data() only works from inside the same process
as the running pipeline. For cross-process data access, use read_sensor_log.py
to query sensor_log.csv — that file is the shared bridge on disk.
