# Define a main functions which can be used mailnly at the end
# Sub functions, if not necessary might not be good idea if not used.
# checkout main class and sub class
#gamma is constal 
import math


def water_volume_loss_to_evaporation(reference_evapotranspiration: float, surface_area_of_pot: float)-> float:
    water_volume_loss = reference_evapotranspiration * surface_area_of_pot
    return water_volume_loss

def crop_evapotranspiration(reference_evapotranspiration: float,
                            balcony_microclimate_correction: float = 1.0, 
                            crop_coefficient: float = 1.0)-> float:
    ET = crop_coefficient * balcony_microclimate_correction * reference_evapotranspiration
    return ET

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

def reference_evapotranspiration(temperature_in_Celsius: float,
                                 wind_speed: float,
                                 soil_moisture_content: float,
                                 min_soil_moisture_content: float,
                                 max_soil_moisture_content: float,
                                 canopy_energy_absorption: float,
                                 soil_energy_absorption: float,
                                 air_density: float = 1.225,
                                 relative_humidity: float = 50.0,
                                 pschometic_constant: float = 0.066,
                                 isobar_specific_of_air: float = 1005
                                 )->float:
    
    latent_heat_of_evaporation = 2.501 - 0.00236 * temperature_in_Celsius
    
    slope_vapour_pressure = (4098 * (0.6108 * math.exp((17.27 * (temperature_in_Celsius + 273.15)) / ((temperature_in_Celsius + 273.15) + 237.3))))/ \
        (((temperature_in_Celsius + 273.15) + 237.3) ** 2)
    
    saturation_vapour_pressure = 0.6108 * math.exp((17.27 * (temperature_in_Celsius + 273.15)) / ((temperature_in_Celsius + 273.15) + 237.3))
    actual_vapour_pressure = saturation_vapour_pressure * (relative_humidity/100) 
    vapour_pressure_deficit = saturation_vapour_pressure - actual_vapour_pressure

    reference_crop = 208/wind_speed
    aerodynamic_conductance = 1/reference_crop

    canopy_resistance = 70 
    canopy_conductance = 1/canopy_resistance

    soil_moisture_factor = (soil_moisture_content - min_soil_moisture_content) / (max_soil_moisture_content - min_soil_moisture_content)

    
    # numerator (first term)
    numerator1 = slope_vapour_pressure * canopy_energy_absorption + \
                (air_density * isobar_specific_of_air / pschometic_constant) * \
                vapour_pressure_deficit * aerodynamic_conductance
    
    # denominator (first term)
    denominator1 = slope_vapour_pressure + 1 + (aerodynamic_conductance / canopy_conductance)

    term1 = numerator1 / denominator1


    # second term
    term2 = (soil_moisture_factor * slope_vapour_pressure * soil_energy_absorption) / (slope_vapour_pressure + 1)

    #reference evapotranspiration
    ref_ET = (term1 + term2) / latent_heat_of_evaporation
    return ref_ET

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







    
    

