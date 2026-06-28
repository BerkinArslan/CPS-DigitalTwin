from pipeline_with_fallback import EnvironmentPipeline, WeatherFallback

# Placeholder coordinates used ONLY before the first P07 message arrives.
# P07 (Team 7) publishes the real sensor location on startup and every 2h.
# The pipeline overwrites these automatically when it receives P07's
# "location" field. Set to None if you prefer the pipeline to skip
# OpenMeteo calls entirely until P07 provides real coordinates.
INITIAL_LATITUDE  = 52.52     ### replace with your city's rough coords if desired
INITIAL_LONGITUDE = 13.405    ### or set both to None to wait for P07

# Rolling window for the averaging buffer.
# All values older than this (in seconds) are dropped before computing
# the average exposed by get_average() and get_data().
# 300 = 5 minutes. Adjust to match how often sensors publish.
WINDOW_SECONDS = 300

### confirm the real broker address/port with P04 (MQTT Infrastructure)
BROKER = "broker.hivemq.com"
PORT   = 1883

if __name__ == "__main__":
    # WeatherFallback starts with placeholder coords.
    # The pipeline will update .latitude / .longitude when P07 publishes
    # its first message containing the "location" JSON field.
    weather_fallback = WeatherFallback(
        latitude=INITIAL_LATITUDE,
        longitude=INITIAL_LONGITUDE,
    )

    pipeline = EnvironmentPipeline(
        broker=BROKER,
        port=PORT,
        weather_fallback=weather_fallback,
        window_seconds=WINDOW_SECONDS,
        # connect=True by default -- only set False in unit tests
    )

    try:
        pipeline.start()   # blocks; runs validation + fallback on every message
    except KeyboardInterrupt:
        print("\n[Pipeline] Stopped by user.")
