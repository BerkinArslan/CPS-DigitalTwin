from pipeline_with_fallback import EnvironmentPipeline, WeatherFallback

fallback = WeatherFallback(52.52, 13.405)
pipeline = EnvironmentPipeline(broker= "broker.hivemq.com", port=1883, weather_fallback= fallback)

pipeline.get_data("temperature_c")
pipeline.get_data("calibrated")
pipeline.get_average("calibrated")
pipeline.get_data()