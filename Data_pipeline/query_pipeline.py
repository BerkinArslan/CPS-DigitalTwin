"""
query_pipeline.py — Digital Twin Query Script
=============================================
Connects to the MQTT broker, collects live sensor data, prints snapshots and
historical summaries, then watches for new readings indefinitely and publishes
digital twin output to the broker.

HOW TO RUN:
  Terminal 1: python environment_simulator.py   (simulates sensor data)
  Terminal 2: python query_pipeline.py          (this script)

THREE THREADS RUN IN PARALLEL ONCE THIS SCRIPT STARTS:
  1. Main thread     — runs Sections 1–3 and then the while True polling loop
  2. Pipeline thread — started by pipeline.start(), listens for MQTT messages in background
  3. Publish thread  — started by publish_client.loop_start(), handles keepalive pings
                       and ensures publish() calls actually go through

All three threads share the same terminal, which is why you see [P03]/[P07]/[WARNING]
messages mixed in with [Poll]/[Query] lines — each thread prints whenever it has output.
"""

import time
import json
import paho.mqtt.client as mqtt
from pipeline_with_fallback import EnvironmentPipeline, WeatherFallback
from read_sensor_log import load_log, get_field, get_values, summary


# =============================================================================
# CONFIGURATION
# =============================================================================

BROKER            = "broker.hivemq.com"
PORT              = 1883
INITIAL_LATITUDE  = 52.52    # Berlin — updated automatically when P07 sends location
INITIAL_LONGITUDE = 13.405
WINDOW_SECONDS    = 300      # rolling window for get_average() — 5 minutes
WAIT_SECONDS      = 10       # seconds to wait for live data before running Section 1


# =============================================================================
# PIPELINE AND PUBLISH CLIENT SETUP
# =============================================================================

print("\n" + "=" * 60)
print("  QUERY PIPELINE — Live + Historical Data")
print("=" * 60)

weather_fallback = WeatherFallback(
    latitude=INITIAL_LATITUDE,
    longitude=INITIAL_LONGITUDE,
)

pipeline = EnvironmentPipeline(
    broker=BROKER,
    port=PORT,
    weather_fallback=weather_fallback,
    window_seconds=WINDOW_SECONDS,
)

# start() is non-blocking — it launches the MQTT listener on a background thread
# and returns immediately. The pipeline collects data quietly in the background.
pipeline.start()

# A separate MQTT client just for publishing digital twin output.
# loop_start() runs MQTT network I/O in a background thread — this keeps the
# connection alive (sends keepalive pings) and ensures publish() calls actually
# go through to the broker. Without it, publish() may silently drop messages.
publish_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
publish_client.connect(BROKER, PORT)
publish_client.loop_start()

print(f"\n[Query] Connected. Waiting {WAIT_SECONDS}s to collect live data...")
print("[Query] (Make sure environment_simulator.py is running in another terminal)\n")
time.sleep(WAIT_SECONDS)


# =============================================================================
# NEW-DATA DETECTION
#
# The pipeline stores value_buffer[field] = [(unix_time, value), ...]
# The most recent entry's timestamp tells us WHEN the last trusted reading arrived.
# We compare it against last_seen[field] to know if anything actually changed.
#
# Why last_seen? We loop every 1 second but new readings arrive every ~5 seconds.
# Without last_seen we would act on the same reading five times in a row.
# =============================================================================

last_seen = {}  # remembers the last timestamp we acted on: {field: unix_time}


def get_field_timestamp(field_name):
    buf = pipeline.value_buffer.get(field_name, [])
    # buf is a list of (unix_time, value) pairs.
    # buf[-1]    → the most recent pair  (last item in the list)
    # buf[-1][0] → its unix timestamp    (first element of the tuple)
    return buf[-1][0] if buf else None


def is_new_data(field_name):
    """
    Returns True only if a NEW reading arrived for this field since the last
    time we called is_new_data(field_name). Updates last_seen automatically.
    """
    current_ts = get_field_timestamp(field_name)

    if current_ts is None:
        return False                          # no data yet

    if field_name not in last_seen:
        last_seen[field_name] = current_ts
        return True                           # first time checking — treat as new

    if current_ts != last_seen[field_name]:
        last_seen[field_name] = current_ts
        return True                           # timestamp changed — genuinely new reading

    return False                              # same timestamp — nothing new


def publish_twin_output(client, timestamp, residual, predicted=0.0):
    """Publishes digital twin output to the P15 topic for P08 (Anomaly Detection)."""
    topic   = "cps/p15/NDATA/digital-twin-main"
    payload = json.dumps({
        "timestamp": timestamp,
        "predicted": predicted,
        "residual":  residual,
        "input_window_ms": 15000,  # inputs came from within ±15 seconds of this timestamp
    })
    client.publish(topic, payload)


# =============================================================================
# SECTION 1 — LATEST VALUES (get_data)
#
# get_data("field") returns the single most recent trusted value.
# "Trusted" means it passed Plan A validation or was filled by Plan B fallback.
# Returns None if no reading has arrived yet.
# =============================================================================

print("=" * 60)
print("  SECTION 1 — Latest Values  (get_data)")
print("=" * 60)

temperature = pipeline.get_data("temperature_c")
print(f"\n[P03] temperature_c  = {temperature} °C")

humidity = pipeline.get_data("humidity_rel")
print(f"[P03] humidity_rel   = {humidity} %")

pressure = pipeline.get_data("pressure_hpa")
print(f"[P03] pressure_hpa   = {pressure} hPa")

light = pipeline.get_data("light_lux")
print(f"[P03] light_lux      = {light} lux")

soil = pipeline.get_data("calibrated")
print(f"\n[P01] calibrated     = {soil}  (0.0=dry, 1.0=saturated)")

raw = pipeline.get_data("raw_adc")
print(f"[P01] raw_adc        = {raw}")

wind = pipeline.get_data("wind_speed")
print(f"\n[P07] wind_speed     = {wind} km/h  (at 2 m height)")

weather_status = pipeline.get_data("weather/status")
print(f"\n[P07] weather/status   = {weather_status}")

location = pipeline.get_data("weather/location")
print(f"[P07] weather/location = {location}")

print("\n--- Full snapshot (all fields) ---")
all_values = pipeline.get_data()
for field, value in all_values.items():
    print(f"  {field} = {value}")


# =============================================================================
# SECTION 2 — ROLLING AVERAGES (get_average)
#
# Mean of all trusted readings within the last WINDOW_SECONDS (5 min default).
# Useful for smoothing noisy sensor readings.
# =============================================================================

print("\n" + "=" * 60)
print("  SECTION 2 — Rolling Averages  (get_average)")
print("=" * 60)

avg_temp     = pipeline.get_average("temperature_c")
avg_humidity = pipeline.get_average("humidity_rel")
avg_pressure = pipeline.get_average("pressure_hpa")
avg_wind     = pipeline.get_average("wind_speed")
avg_soil     = pipeline.get_average("calibrated")

print(f"\n[P03] temperature_c  5min avg = {avg_temp} °C")
print(f"[P03] humidity_rel   5min avg = {avg_humidity} %")
print(f"[P03] pressure_hpa   5min avg = {avg_pressure} hPa")
print(f"[P07] wind_speed     5min avg = {avg_wind} km/h")
print(f"[P01] calibrated     5min avg = {avg_soil}")


# =============================================================================
# SECTION 3 — HISTORICAL DATA (sensor_log.csv)
#
# The pipeline writes every trusted reading to disk. Keeps up to 8 hours.
#
# load_log()              → all rows as a list of dicts
# get_field(rows, field)  → filter to one field only
# get_values(rows, field) → plain list of numeric values for math
# summary(rows, field)    → prints mean, min, max, std dev
# =============================================================================

print("\n" + "=" * 60)
print("  SECTION 3 — Historical Data  (sensor_log.csv)")
print("=" * 60)

all_rows = load_log()

if not all_rows:
    print("\n[Query] No CSV data found. Run the pipeline first to generate data.")
else:
    first_time = all_rows[0]["timestamp_utc"]
    last_time  = all_rows[-1]["timestamp_utc"]
    print(f"\n[CSV] Total rows: {len(all_rows)}")
    print(f"[CSV] Data from {first_time} to {last_time}")

    print("\n--- Statistical summary per field ---")
    for field in ["temperature_c", "humidity_rel", "pressure_hpa",
                  "light_lux", "wind_speed", "calibrated", "raw_adc"]:
        values = get_values(all_rows, field)
        if values:
            summary(all_rows, field)
            print()

    print("--- Last 10 temperature_c readings ---")
    temp_rows = get_field(all_rows, "temperature_c")
    for row in temp_rows[-10:]:
        print(f"  {row['timestamp_utc']}  temperature_c = {row['value']} °C")

    print("\n--- Last 10 wind_speed readings ---")
    wind_rows = get_field(all_rows, "wind_speed")
    if wind_rows:
        for row in wind_rows[-10:]:
            print(f"  {row['timestamp_utc']}  wind_speed = {row['value']} km/h")
    else:
        print("  No wind_speed data yet — P07 has not published this field.")

    print("\n--- Last 10 calibrated (soil moisture) readings ---")
    soil_rows = get_field(all_rows, "calibrated")
    for row in soil_rows[-10:]:
        print(f"  {row['timestamp_utc']}  calibrated = {row['value']}")

    temp_values = get_values(all_rows, "temperature_c")
    if temp_values:
        historical_avg = sum(temp_values) / len(temp_values)
        print(f"\n[CSV] Historical avg temperature  = {historical_avg:.2f} °C  ({len(temp_values)} readings)")

    soil_values = get_values(all_rows, "calibrated")
    if soil_values:
        historical_avg = sum(soil_values) / len(soil_values)
        print(f"[CSV] Historical avg soil moisture = {historical_avg:.3f}  ({len(soil_values)} readings)")


# =============================================================================
# POLLING LOOP
# Watches for new sensor readings and publishes digital twin output.
# Runs until Ctrl+C.
# =============================================================================

print("\n[Query] Watching for new readings. Ctrl+C to stop.\n")
try:
    while True:
        if is_new_data("temperature_c"):
            temp = pipeline.get_data("temperature_c")
            if temp is not None:
                temp_f = round(temp * 9/5 + 32, 2)
                print(f"[Query] New temperature_c: {temp} °C  ({temp_f} °F)")

        if is_new_data("calibrated"):
            actual        = pipeline.get_data("calibrated")
            timestamp_p01 = pipeline.get_p01_timestamp()
            predicted     = 0.0
            residual      = round(predicted - actual, 4)
            publish_twin_output(publish_client, timestamp_p01, residual, predicted)
            print(f"[Poll] New soil moisture: {actual}")

        time.sleep(1)

except KeyboardInterrupt:
    pipeline.stop()
    print("\n[Query] Disconnected from broker. Exiting.")
