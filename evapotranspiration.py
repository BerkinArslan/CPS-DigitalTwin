# Define a main functions which can be used mailnly at the end
# Sub functions, if not necessary might not be good idea if not used.
# checkout main class and sub class
#gamma is constal 
import math
import numpy as np

def water_volume_loss_to_evaporation(
        et_crop: float,
        pot_area: float
)-> float:

    water_volume_loss = et_crop * pot_area
    return water_volume_loss


def crop_evapotranspiration(
        reference_et: float,
        crop_coefficient: float = 1.0,
        balcony_microclimate_correction: float = 1.0,
)-> float:
    et_crop = balcony_microclimate_correction * crop_coefficient * reference_et
    return et_crop

# def reference_evapotransiration(slope_vapour_pressure: float, 
#                                 net_radiation: float,
#                                 soil_heat_flux_density: float, 
#                                 air_temperature: float,
#                                 wind_speed: float,
#                                 saturation_vapour_pressure: float,
#                                 actual_vapout_pressure: float,
#                                 gamma=0.5)-> float:
#     numerator = 0.408 * slope_vapour_pressure  * (net_radiation - soil_heat_flux_density) \
#         + gamma * (900 / (air_temperature + 273)) * wind_speed *\
#         (saturation_vapour_pressure - actual_vapout_pressure)
#     denominator = slope_vapour_pressure + gamma * (1 + (0.34 * wind_speed))
#     ref_ET = numerator / denominator
#     return ref_ET

def reference_evapotranspiration(
        temp_c: float, #C
        wind_speed: float, #m/s
        soil_moisture: float,
        min_soil_moisture: float,
        max_soil_moisture: float,
        canopy_energy_absorption: float, #MJ/m^2*day
        soil_energy_absorption: float, #MJ/m^2*day
        air_density: float = 1.225, #kg/m^3
        relative_humidity: float = 50.0, #percentage
        psychometric_constant: float = 0.066,
        isobar_specific_of_air: float = 0.001005
)->float:
    
    latent_heat_of_evaporation = 2.501 - 0.00236 * temp_c
    
    # slope_vapour_pressure = (4098 * (0.6108 * math.exp((17.27 * (temp_c + 273.15)) / ((temp_c + 273.15) + 237.3))))/ \
    #     (((temp_c + 273.15) + 237.3) ** 2)

    slope_vapour_pressure = (
    (4098 * (0.6108 * np.exp((17.27 * temp_c ) / (temp_c + 237.3)))) /
    ((temp_c + 237.3) ** 2)
    )

    slope_vapour_pressure_ratio = slope_vapour_pressure / psychometric_constant
    
    saturation_vapour_pressure = 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))

    actual_vapour_pressure = saturation_vapour_pressure * (relative_humidity / 100)

    vapour_pressure_deficit = saturation_vapour_pressure - actual_vapour_pressure

    aerodynamic_conductance = wind_speed / 208

    canopy_resistance = 70 
    canopy_conductance = 1 / canopy_resistance

    soil_moisture_factor = (soil_moisture - min_soil_moisture) / (max_soil_moisture - min_soil_moisture)

    # numerator (first term)
    numerator1 = slope_vapour_pressure_ratio * canopy_energy_absorption + \
                 (air_density * isobar_specific_of_air / psychometric_constant) * \
                 vapour_pressure_deficit * aerodynamic_conductance * 86400
    
    # denominator (first term)
    denominator1 = slope_vapour_pressure_ratio + 1 + (aerodynamic_conductance / canopy_conductance)

    term1 = numerator1 / denominator1


    # second term
    term2 = ((soil_moisture_factor * slope_vapour_pressure_ratio * soil_energy_absorption)
             / (slope_vapour_pressure_ratio + 1))

    #reference evapotranspiration
    ref_et = (term1 + term2) / latent_heat_of_evaporation
    return ref_et

"""
λE = [ Δ·A_c + (ρ·c_p/γ)·D_a·G_a ] / [ Δ + 1 + (G_a/G_c) ] 
    + ( f·Δ·A_s ) / ( Δ + 1 )

ET = λE / λ

Δ  = slope_vapour_pressure
A_c = canopy_energy_absorption
A_s = soil_energy_absorption
ρ  = air_density
c_p = isobar_specific_of_air
γ  = pschometic_constant
D_a = vapour_pressure_deficit
G_a = aerodynamic_conductance
G_c = canopy_conductance
f  = soil_moisture_factor
λ  = latent_heat_of_evaporation
ET = reference_evapotranspiration
"""

if __name__ == "__main__":

    t_celcius = 22 #C
    wind_speed = 5 #m/s
    soil_moisture = 0.45
    max_soil_moisture = 1.0
    min_soil_moisture = 0.0
    net_irradiation_berlin = 300 #W/m^2


    irradiation_work = net_irradiation_berlin * 24 * 3600 / 1e6 #W/m^2 * s/day = J/m^2*day
    irradiation_work = irradiation_work

    plant_canopy_energy_absorption = irradiation_work * 0.3 * 0.45 # 45% evopration efficiency of canopy
    soil_energy_absorption = irradiation_work * 0.7 * 0.8 #20% albedo

    ref_ET = reference_evapotranspiration(t_celcius,
                                     wind_speed,
                                     soil_moisture,
                                     min_soil_moisture,
                                     max_soil_moisture,
                                     plant_canopy_energy_absorption,
                                     soil_energy_absorption,
                                     )

    ET = crop_evapotranspiration(ref_ET, crop_coefficient=1, balcony_microclimate_correction=0.7)

    water_loss = water_volume_loss_to_evaporation(ET, 0.08)

    print(f'water loss after one day: {water_loss}')











    
    

