from evapotranspiration import water_volume_loss_to_evaporation
from system import IrrigationSystem
from nodes import Pot
from Data_pipeline.pipeline_with_fallback import EnvironmentPipeline, WeatherFallback

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

