from pipeline_with_fallback import EnvironmentPipeline, WeatherFallback
 
# Berlin coordinates -- replace with your actual balcony location if different
LATITUDE = 52.52
LONGITUDE = 13.405
 
### fill in: confirm the real broker address/port with P04 (MQTT Infrastructure)
BROKER = "broker.hivemq.com"
PORT = 1883
 
if __name__ == "__main__":
    # weather_fallback only serves temperature_c and humidity_pct -- it has
    # no role for soil moisture, pump, or watering-controller fields, which
    # use LastKnownValueFallback / NoFallback instead (built inside the
    # EnvironmentPipeline itself).
    weather_fallback = WeatherFallback(latitude=LATITUDE, longitude=LONGITUDE)
    pipeline = EnvironmentPipeline(broker=BROKER, port=PORT, weather_fallback=weather_fallback)
    try:
       pipeline.start()  # blocks here, runs validation + fallback chain on every message
    except KeyboardInterrupt:
        print("\n[Pipeline] Stopped by user.")