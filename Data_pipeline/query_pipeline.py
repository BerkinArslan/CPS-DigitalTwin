"""
query_pipeline.py — Live + Historical Data Query Script
========================================================
This script shows how to use the pipeline to get live sensor data
and how to query historical data from the CSV log.

HOW TO RUN:
  Terminal 1: python environment_simulator.py   (fakes sensor data)
  Terminal 2: python query_pipeline.py          (this script)

You do NOT need run_pipeline.py running at the same time.
This script creates its own pipeline object internally.

WHAT THIS SCRIPT DOES:
  1. Connects to the MQTT broker
  2. Waits 10 seconds to collect live sensor data
  3. Prints latest values using get_data()
  4. Prints rolling averages using get_average()
  5. Prints historical summaries from sensor_log.csv
  6. Disconnects and exits
"""

import time
import sys
import os

# We import the pipeline class and fallback class from our main file.
# This is exactly like doing "import numpy as np" -- we are just
# importing tools someone else already built.
from pipeline_with_fallback import EnvironmentPipeline, WeatherFallback


# =============================================================================
# EVENT-DRIVEN CALLBACK
#
# on_new_reading is called automatically by the pipeline on every MQTT message.
# The pipeline passes two things:
#   snapshot  — dict of all latest trusted values at this moment
#   status    — the status string that arrived with THIS message
#               e.g. "ok", "sensor_error", "out_of_range", "stale"
#               None on heartbeat ticks (no incoming message)
#
# The if status == "ok" block only runs when the data came directly from
# the real sensor (Plan A). If the pipeline used a fallback (OpenMeteo,
# last-known), status will be something else and the block is skipped.
# =============================================================================

def on_new_reading(snapshot, status):
    if status in ("ok", "live"):
        temp = snapshot.get("temperature_c")
        if temp is not None:
            temp_f = round(temp * 9 / 5 + 32, 1)
            print(f"[Event] Sensor ok — temperature = {temp} °C  /  {temp_f} °F")

# We import helper functions from read_sensor_log.py for CSV queries.
from read_sensor_log import load_log, get_field, get_values, summary


# =============================================================================
# CONFIGURATION
# Change these if your broker address or coordinates are different.
# =============================================================================

BROKER            = "broker.hivemq.com"
PORT              = 1883
INITIAL_LATITUDE  = 52.52    # Berlin — replaced automatically when P07 sends location
INITIAL_LONGITUDE = 13.405
WINDOW_SECONDS    = 300      # 5 minute rolling window for get_average()
WAIT_SECONDS      = 10       # how long to wait for live data before querying


# =============================================================================
# SECTION 0 — SET UP THE PIPELINE
# Create the pipeline object exactly like creating a numpy array.
# This does not connect yet — connection happens when we call start().
# =============================================================================

print("\n" + "=" * 60)
print("  QUERY PIPELINE — Live + Historical Data")
print("=" * 60)

# WeatherFallback provides Plan B for temperature, humidity, pressure
# when P03 sensor fails. Coordinates are updated automatically by P07.
weather_fallback = WeatherFallback(
    latitude=INITIAL_LATITUDE,
    longitude=INITIAL_LONGITUDE,
)

# Create the pipeline object. connect=True means it will connect to the
# broker immediately when we call start() below.
pipeline = EnvironmentPipeline(
    broker=BROKER,
    port=PORT,
    weather_fallback=weather_fallback,
    window_seconds=WINDOW_SECONDS,
    on_new_reading=on_new_reading,
)

# start() is non-blocking — it launches the MQTT listener on a background
# thread and returns immediately. From this point, the pipeline is
# quietly collecting data in the background.
pipeline.start()
print(f"\n[Query] Connected. Waiting {WAIT_SECONDS} seconds to collect live data...")
print("[Query] (Make sure environment_simulator.py is running in another terminal)\n")

# We wait here to give the pipeline time to receive messages from the
# simulator. Without this wait, latest_values would still be empty
# and get_data() would return None for everything.
time.sleep(WAIT_SECONDS)


# =============================================================================
# SECTION 1 — LATEST VALUES using get_data("field_name")
#
# get_data("field_name") returns the single most recent trusted value
# for that field. "Trusted" means it passed Plan A validation, or was
# filled by Plan B fallback. Returns None if no value has arrived yet.
#
# get_data() with no argument returns ALL latest values as a dict.
# =============================================================================

print("=" * 60)
print("  SECTION 1 — Latest Values  (get_data)")
print("=" * 60)

# --- P03: Environmental sensor ---
# temperature_c: air temperature in Celsius (-40 to 85)
temperature = pipeline.get_data("temperature_c")
print(f"\n[P03] temperature_c  = {temperature} °C")

# humidity_rel: relative humidity percentage (0 to 100)
humidity = pipeline.get_data("humidity_rel")
print(f"[P03] humidity_rel   = {humidity} %")

# pressure_hpa: barometric pressure in hPa (300 to 1100)
pressure = pipeline.get_data("pressure_hpa")
print(f"[P03] pressure_hpa   = {pressure} hPa")

# light_lux: ambient light intensity (0 to 65535)
# Fallback: OpenMeteo shortwave_radiation × 120 → lux approximation.
light = pipeline.get_data("light_lux")
print(f"[P03] light_lux      = {light} lux")

# --- P01: Soil moisture sensor ---
# calibrated: moisture fraction (0.0 = completely dry, 1.0 = fully saturated)
soil = pipeline.get_data("calibrated")
print(f"\n[P01] calibrated     = {soil}  (0.0=dry, 1.0=saturated)")

# raw_adc: raw hardware reading before calibration (0 to 65535)
raw = pipeline.get_data("raw_adc")
print(f"[P01] raw_adc        = {raw}")

# wind_speed: wind speed at 2 m height in km/h (published by P07 on the same topic).
# Fallback: OpenMeteo wind_speed_10m converted to 2 m using the wind power law.
# If P07 has not configured this field yet, returns None until they start publishing.
wind = pipeline.get_data("wind_speed")
print(f"\n[P07] wind_speed     = {wind} km/h  (at 2 m height)")

# --- P07: Weather API ---
# weather/status: tells you if the forecast is fresh, cached, or unavailable
weather_status = pipeline.get_data("weather/status")
print(f"\n[P07] weather/status = {weather_status}")

# weather/location: dict with name, latitude, longitude
location = pipeline.get_data("weather/location")
print(f"[P07] weather/location = {location}")

# --- ALL VALUES AT ONCE ---
# get_data() with no argument returns everything as a dict.
# Useful when you want to pass the full snapshot to another system.
print("\n--- Full snapshot (all fields at once) ---")
all_values = pipeline.get_data()
for field, value in all_values.items():
    print(f"  {field} = {value}")


# =============================================================================
# SECTION 2 — ROLLING AVERAGES using get_average("field_name")
#
# get_average("field_name") computes the mean of all trusted readings
# received within the last WINDOW_SECONDS (5 minutes by default).
# Returns None if no readings exist in the window yet.
#
# This is useful for smoothing out noisy sensor readings.
# Example: one bad spike in temperature does not affect the 5min average much.
# =============================================================================

print("\n" + "=" * 60)
print("  SECTION 2 — Rolling Averages  (get_average)")
print("=" * 60)

# 5 minute rolling average for temperature
avg_temp = pipeline.get_average("temperature_c")
print(f"\n[P03] temperature_c  5min average = {avg_temp} °C")

# 5 minute rolling average for humidity
avg_humidity = pipeline.get_average("humidity_rel")
print(f"[P03] humidity_rel   5min average = {avg_humidity} %")

# 5 minute rolling average for pressure
avg_pressure = pipeline.get_average("pressure_hpa")
print(f"[P03] pressure_hpa   5min average = {avg_pressure} hPa")

# 5 minute rolling average for wind speed
avg_wind = pipeline.get_average("wind_speed")
print(f"[P07] wind_speed     5min average = {avg_wind} km/h")

# 5 minute rolling average for soil moisture
avg_soil = pipeline.get_average("calibrated")
print(f"[P01] calibrated     5min average = {avg_soil}")


# =============================================================================
# SECTION 3 — HISTORICAL DATA from sensor_log.csv
#
# sensor_log.csv is written to disk by the pipeline every time a trusted
# reading is stored. It keeps up to 8 hours of history.
#
# load_log()              → loads all rows from the CSV as a list of dicts
# get_field(rows, field)  → filters rows to only one field
# get_values(rows, field) → returns just the numeric values as a plain list
# summary(rows, field)    → prints mean, min, max, std dev for a field
#
# This section works even without a broker running — it just reads the file.
# =============================================================================

print("\n" + "=" * 60)
print("  SECTION 3 — Historical Data  (sensor_log.csv)")
print("=" * 60)

# Load everything from the CSV into memory as a list of dicts.
# Each dict looks like:
# {"timestamp_unix": 1234567890.0, "timestamp_utc": "2026-06-28T...", "field": "temperature_c", "value": 21.3}
all_rows = load_log()

if not all_rows:
    print("\n[Query] No CSV data found. Run the pipeline first to generate data.")
else:
    # Show the time range available
    first_time = all_rows[0]["timestamp_utc"]
    last_time  = all_rows[-1]["timestamp_utc"]
    print(f"\n[CSV] Total rows: {len(all_rows)}")
    print(f"[CSV] Data from {first_time} to {last_time}")

    # --- Statistical summary for each field ---
    # summary() prints mean, min, max, std dev for a field over the given rows.
    print("\n--- Statistical summary for each field ---")
    fields = ["temperature_c", "humidity_rel", "pressure_hpa",
              "light_lux", "wind_speed", "calibrated", "raw_adc"]
    for field in fields:
        values = get_values(all_rows, field)
        if values:
            summary(all_rows, field)
            print()

    # --- Last 10 readings for temperature ---
    # get_field() returns all rows for one field.
    # We slice [-10:] to get only the most recent 10.
    print("--- Last 10 temperature_c readings ---")
    temp_rows = get_field(all_rows, "temperature_c")
    for row in temp_rows[-10:]:
        print(f"  {row['timestamp_utc']}  temperature_c = {row['value']} °C")

    # --- Last 10 readings for wind speed ---
    print("\n--- Last 10 wind_speed readings ---")
    wind_rows = get_field(all_rows, "wind_speed")
    if wind_rows:
        for row in wind_rows[-10:]:
            print(f"  {row['timestamp_utc']}  wind_speed = {row['value']} km/h")
    else:
        print("  No wind_speed data yet — P07 has not published this field.")

    # --- Last 10 readings for soil moisture ---
    print("\n--- Last 10 calibrated (soil moisture) readings ---")
    soil_rows = get_field(all_rows, "calibrated")
    for row in soil_rows[-10:]:
        print(f"  {row['timestamp_utc']}  calibrated = {row['value']}")

    # --- Manual average from CSV values ---
    # get_values() returns a plain list of floats — you can do any math on it.
    # This is the historical average over the full 8 hour log,
    # NOT the rolling 5 minute average from get_average().
    temp_values = get_values(all_rows, "temperature_c")
    if temp_values:
        historical_avg = sum(temp_values) / len(temp_values)
        print(f"\n[CSV] Historical average temperature = {historical_avg:.2f} °C  ({len(temp_values)} readings)")

    soil_values = get_values(all_rows, "calibrated")
    if soil_values:
        historical_avg = sum(soil_values) / len(soil_values)
        print(f"[CSV] Historical average soil moisture = {historical_avg:.3f}  ({len(soil_values)} readings)")


# =============================================================================
# DONE — disconnect cleanly
# =============================================================================

pipeline.stop()
print("\n" + "=" * 60)
print("  QUERY COMPLETE")
print("=" * 60 + "\n")
