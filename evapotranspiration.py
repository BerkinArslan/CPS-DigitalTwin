# Define a main functions which can be used mailnly at the end
# Sub functions, if not necessary might not be good idea if not used.
# checkout main class and sub class
#gamma is constal 

def evapotranspiration(crop_coefficient: float,
                        reference_evapotranspiration: float)-> float:
    ET = crop_coefficient * reference_evapotransiration
    return ET

def reference_evapotransiration(slope_vapour_pressure: float, 
                                net_radiation: float,
                                soil_heat_flux_density: float, 
                                air_temperature: float,
                                wind_speed: float,
                                saturation_vapour_pressure: float,
                                actual_vapout_pressure: float)-> float:
    gamma = 0.5
    ref_ET = 0.408 * slope_vapour_pressure  * (net_radiation - soil_heat_flux_density) \
        + gamma * (900 / (air_temperature + 273)) * wind_speed *\
        (saturation_vapour_pressure - actual_vapout_pressure)/ slope_vapour_pressure + \
        gamma * (1 + (0.34 * wind_speed))
    return ref_ET
