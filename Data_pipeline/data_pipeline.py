# FIND THE BROKER NAME 
# BUILT OWN UNIT STANDARIZATION
# LOOK AT SOIL_MOISTURE_DATA GUIDE FROM GROUP 1 IN WHATSAPP
# Put time step later in the class we create for the pipeline. No hard code
# RESAMPLING: If the data is not coming in at regular intervals, we can use resampling techniques to create a consistent time series. For example, if 
# we want to have data points every minute, we can resample the incoming data to fill in any gaps or aggregate multiple readings into a single value 
# for that minute. This can be done using libraries like pandas in Python, which provides powerful tools for resampling time series data.
# METHOD FOR UNIT CONVERSION: In case, if temperature is provided in fahrenheit, convert it to celsius.

import paho.mqtt.client as mqtt
import pandas as pd

class DataPipeline:
    def __init__(self, broker, topic, port):
        self.broker = broker
        self.topic = topic
        self.port = port

    def on_message(self, client, userdata, message):
        value = float(message.payload.decode())
        print(f"from {message.topic}, value = {value}")

    def fahr_to_celsius(self, temperature):
        temperature_c = (temperature - 32) * 5/9
        return temperature_c
    
    def resample_data(self, data, time_interval):
        mean_1h = data.resample(time_interval).mean()
        return mean_1h

    # DATA RESAMPLING — what it is and why it works
    #
    # Each incoming sensor reading carries its own timestamp (e.g. "2026-06-10T10:54:31Z").
    # Resampling works by reading these timestamps directly — it does not need to know
    # that data arrives every 21 seconds. It simply looks at when each value was recorded
    # and groups all values that fall within the same time window (e.g. the same hour).
    #
    # So when you call resample("1h").mean(), pandas scans all timestamps,
    # collects every reading that landed between 10:00 and 11:00 into one bucket,
    # computes their mean, then moves to the next bucket (11:00–12:00), and so on.
    # The original publish interval is irrelevant — even if readings were irregular
    # or some were missing, the timestamps alone tell pandas where each value belongs.
    #
    # This is the difference between resampling and a fixed-interval counter:
    # a counter would say "wait 21 seconds, collect, repeat".
    # Resampling says "give me all values, I will sort them by time myself".
        
    def subscribe(self):
        client = mqtt.Client()
        client.connect(self.broker, self.port)
        client.on_message = self.on_message
        client.subscribe(self.topic)
        #client.loop_forever() skip loop_forever() for now, in order to have more control over the flow of the 
        print("hello")
        """
        At first I was confused about what it means that loop_forever() “blocks” the program, because it was not clear what exactly is running 
        and why nothing else executes afterward. What I understood is that loop_forever() internally contains an infinite loop that continuously 
        listens for incoming MQTT messages from the broker. Once the program reaches this line, it stays inside that loop and repeatedly checks for 
        new data, and whenever a message arrives, it calls the on_message function. Because the program is stuck inside this infinite listening loop, 
        it never moves on to any code written after loop_forever(), which is why it is called “blocking.”
        """

    