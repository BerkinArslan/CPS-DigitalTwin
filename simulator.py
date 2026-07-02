from evapotranspiration import water_volume_loss_to_evaporation
from system import IrrigationSystem
from nodes import Pot
from Data_pipeline.pipeline_with_fallback import EnvironmentPipeline, WeatherFallback
import time
from Data_pipeline.run_pipeline import on_new_reading

class Simulation:

    def __init__(self,
                 system: IrrigationSystem,
                 crop_coefficient: float = 1,
                 balcony_mc_coefficient: float = 0.75,
                 evaporation_efficiency: float = 0.45,):
        self.system = system
        self.crop_coefficient = crop_coefficient
        self.balcony_mc_coefficient = balcony_mc_coefficient
        self.evaporation_efficiency = evaporation_efficiency

    def step_advanced(self,
             step_time: float,
             t_celcious: float,
             wind_speed: float,
             irradiation: float,
             soil_albedo: float,
             soil_absorption_ratio: float,
             schedule: int = 0):
        """
        runs the simulation step
        :param step_time: length of the step in seconds
        :param t_celcious: temperature in celcius
        :param wind_speed: speed of the wind in m/s
        :param irradiation: irradiation value in w/m^2
        :param soil_albedo: albedo ratio of the soil
        :param soil_absorption_ratio: absorption ratio of the soil
        :param schedule: only when there is multiple steps to be simulated
        :return: updated status values of the system
        """

        pipe_volumes = self.system.flow_simulation_step(schedule)
        self.system.evapotranspiration_simulation_step(
            step_time,
            t_celcious,
            wind_speed,
            irradiation,
            soil_albedo,
            soil_absorption_ratio,
            self.crop_coefficient,
            self.balcony_mc_coefficient,
            self.evaporation_efficiency
        )

    def step_simple(self,
                    et_0: float,
                    step_time: float,
                    schedule: int = 0):
        """
        Runs the simulation with the OpenMeteo ET_0 value
        :param et_0: OpenMeteo ET_0 value
        :param step_time: length of the step in seconds
        :param schedule: schedule of the simulation when multiple steps are simulated
        :return: updated states of the system
        """

        pipe_volumes = self.system.flow_simulation_step(schedule)

        divider = step_time / (60 * 60 * 24)
        et = self.balcony_mc_coefficient * self.crop_coefficient * et_0
        et = et * divider

        pots = [pot for pot_name, pot in self.system.nodes.items() if isinstance(pot, Pot)]
        for pot in pots:
            water_volume_loss = water_volume_loss_to_evaporation(et, pot.pot_area)
            pot.water_volume = pot.water_volume - water_volume_loss
            pot.update_moisture()

class Auto_Predict_Simulator(Simulation):

    def __init__(self,
                 data_pipeline: EnvironmentPipeline,
                 data_fallback: WeatherFallback,
                 system: IrrigationSystem,
                 crop_coefficient: float = 1,
                 balcony_mc_coefficient: float = 0.75,
                 evaporation_efficiency: float = 0.45,):
        super().__init__(system,
                         crop_coefficient,
                         balcony_mc_coefficient,
                         evaporation_efficiency)

        self.data_pipeline = data_pipeline
        self.data_fallback = data_fallback
        #TODO:
        # make this connect ot the MQTT and make prediction automatically
        # decide on averaging window or last value
        # maybe snapshot methods would work better for this workflow. It outputs None

        data_pipeline.start()

        try:
            while True:
                time.sleep(1)
                # TODO: find how to if query to see if there is a new moisture reading
                temp_c = data_pipeline.get_data('temperature_c')
                humidity = data_pipeline.get_data('humidity')
                pressure = data_pipeline.get_data('pressure')
                irradiation = data_pipeline.get_data('light_lux')
                soil_moisture = data_pipeline.get_data('soil_moisture')

                print(f"Temperature: {temp_c}\n"
                      f"Humidity: {humidity}\n"
                      f"Air pressure: {pressure}\n"
                      f"Soil moisture: {soil_moisture}\n"
                      f"Irradiation: {irradiation}\n")
        except KeyboardInterrupt:
            data_pipeline.stop()


if __name__ == "__main__":
    INITIAL_LATITUDE = 52.52
    INITIAL_LONGITUDE = 13.405

    WINDOW_SECONDS = 5
    BROKER = "broker.hivemq.com"
    PORT = 1883

    #TODO: Ask Rohel:
    # what does window_seconds do?
    # What does interval secconds do?
    # What does  interval_seconds do?

    fallback = WeatherFallback(
        INITIAL_LATITUDE,
        INITIAL_LONGITUDE,
    )
    data_pipeline = EnvironmentPipeline(
        BROKER,
        PORT,
        fallback,
        WINDOW_SECONDS,
        on_new_reading=on_new_reading,
        interval_seconds=30
    )

    sys = IrrigationSystem()
    sys.add_water_tank(
        name="Tank1",
        coordinates=(0, 0),
        elevation=0,
        max_head=1.5,
        min_head=0,
        max_volume=100,
        initial_volume=50
    )

    sys.add_pot(
        name="Pot1",
        coordinates=(1, 0),
        elevation=0,
        soil_volume=10,
        max_moisture=1.0,
        min_moisture=0.0,
        initial_moisture=0.5
    )

    sys.add_pump(
        name="Pump1",
        start_node='Tank1',
        end_node='Pot1',
        length=1,
        diameter=0.001,
        roughness=None,
        power=None,
        flow_rate=0.25,
        activation_time=0
    )

    simulator = Auto_Predict_Simulator(
        data_pipeline,
        fallback,
        sys,
    )




