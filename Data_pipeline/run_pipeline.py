import time
from pipeline_with_fallback import EnvironmentPipeline, WeatherFallback

# Placeholder coordinates used ONLY before the first P07 message arrives.
# P07 overwrites these automatically when it sends its first location field.
INITIAL_LATITUDE  = 52.52
INITIAL_LONGITUDE = 13.405

WINDOW_SECONDS    = 300
BROKER            = "broker.hivemq.com"
PORT              = 1883

# =============================================================================
# CALLBACK — called automatically on every new MQTT message AND every 30s
# heartbeat. snapshot is a copy of latest_values at that moment.
# Replace the print statement here with whatever your digital twin needs.
# =============================================================================
def on_new_reading(snapshot, status):
    temp     = snapshot.get("temperature_c")
    humidity = snapshot.get("humidity_rel")
    moisture = snapshot.get("calibrated")
    print(f"[Twin] temp={temp}  humidity={humidity}  soil={moisture}")

    if status in ("ok", "live"):
        if temp is not None:
            temp_f = round(temp * 9 / 5 + 32, 1)
            print(f"[Twin] Sensor confirmed ok — temperature = {temp_f} °F")

if __name__ == "__main__":
    weather_fallback = WeatherFallback(
        latitude=INITIAL_LATITUDE,
        longitude=INITIAL_LONGITUDE,
    )

    pipeline = EnvironmentPipeline(
        broker=BROKER,
        port=PORT,
        weather_fallback=weather_fallback,
        window_seconds=WINDOW_SECONDS,
        on_new_reading=on_new_reading,
        interval_seconds=30,
    )

    pipeline.start()
    print("[Pipeline] Running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pipeline.stop()