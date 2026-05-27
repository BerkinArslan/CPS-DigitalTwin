# Define a main functions which can be used mailnly at the end
# Sub functions, if not necessary might not be good idea if not used.
# checkout main class and sub class
#gamma is constal 

def water_volume_loss_to_evaporation()-> float:
    
    pass

def crop_evapotranspiration(reference_evapotranspiration: float,
                            balcony_microclimate_correction: float = 1.0, 
                            crop_coefficient: float = 1.0)-> float:
    ET = crop_coefficient * balcony_microclimate_correction * reference_evapotranspiration
    return ET

def reference_evapotransiration(slope_vapour_pressure: float, 
                                net_radiation: float,
                                soil_heat_flux_density: float, 
                                air_temperature: float,
                                wind_speed: float,
                                saturation_vapour_pressure: float,
                                actual_vapout_pressure: float,
                                gamma=0.5)-> float:
    numerator = 0.408 * slope_vapour_pressure  * (net_radiation - soil_heat_flux_density) \
        + gamma * (900 / (air_temperature + 273)) * wind_speed *\
        (saturation_vapour_pressure - actual_vapout_pressure)
    denominator = slope_vapour_pressure + gamma * (1 + (0.34 * wind_speed))
    ref_ET = numerator / denominator
    return ref_ET
