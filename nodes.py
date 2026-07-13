"""

Includes object classes for node-type objects

"""
class Node:
    """
    Node Object includes global parameters for all nodes
    """
    def __init__(self,
                 name: str,
                 coordinates: tuple[float, float],
                 elevation: float,
                 ):
        """
        Creates a new node with global parameters
        :param name:
        :param coordinates:
        """
        self.name = name
        self.coordinates = coordinates
        self.elevation = elevation
        self.incoming_links = []
        self.outgoing_links = []


class WaterTank(Node):
    """
    Represents water storage tank in systems
    """
    def __init__(self,
                 name: str,
                 coordinates: tuple[float, float],
                 elevation: float,
                 max_head: float,
                 min_head: float,
                 max_volume: float,
                 initial_volume: float,):
        """
        Creates a new water tank object.
        :param name: Name of the water tank.
        :param coordinates: x, y coordinates of water tank.
        :param elevation: Elevation of the water tank from global reference point (eg; ground)
        :param max_head: Maximum potential energy derived from the maximum top level of water.
        :param min_head: Minimum potential energy derived from the minimum top level of water.
        :param max_volume: Maximum water capacity of the water tank.
        :param initial_volume: Water volume in the water tank at the initial time.
        :return: None
        """
        super().__init__(name, coordinates, elevation)
        #Static states:
        self.max_head = max_head
        self.min_head = min_head
        self.max_volume = max_volume
        self.initial_volume = initial_volume

        #Dynamic simulation states:
        self.head = ((self.max_head - self.min_head) / self.max_volume) \
                        * self.initial_volume + self.min_head
        self.volume = self.initial_volume

    def update_head(self):
        """
        Recalculates head from the current volume (same linear relation
        as in __init__). Call after every volume change.
        """
        self.head = ((self.max_head - self.min_head) / self.max_volume) \
                        * self.volume + self.min_head
        return self.head

class Pot(Node):
    """
    Represents a pot in systems
    """
    def __init__(self,
                 name: str,
                 coordinates: tuple[float, float],
                 elevation: float,
                 soil_volume: float,
                 max_moisture: float,
                 min_moisture: float,
                 initial_moisture: float,
                 pot_area: float = 0.08,
                 moisture_ref: float = 0.31,       # sensor reading at V = 0 reference (dry-soil reading)
                 cal_slope: float = 0.3349,        # moisture change per liter retained water [1/L]
                 drain_slope: float = -0.2870,     # retained-per-dose vs fill level, slope [-]
                 drain_intercept: float = 0.3047,  # retained-per-dose vs fill level, intercept [L]
                 ):
        """
        Creates a new pot object
        :param name: Name of the pot
        :param coordinates: Coordinates of the pot
        :param elevation: Elevation of the pot from reference point (eg; ground)
        :param soil_volume: Soil volume of the pot
        :param max_moisture: Maximum possible moisture level of the pot
        :param min_moisture: Minimum possible moisture level of the pot
        :param initial_moisture: Moisture level at initiation
        :param moisture_ref: Sensor moisture reading at the calibration reference (V = 0)
        :param cal_slope: Moisture increase per liter of retained water
        :param drain_slope: Slope of retained water per dose vs current fill level
        :param drain_intercept: Intercept of retained water per dose [L]

        Calibration values are computed by soil_moisture_experiment.py from the
        watering experiment (run it to reproduce them).
        """
        super().__init__(name, coordinates, elevation)
        #Static states
        self.soil_volume = soil_volume
        self.max_moisture = max_moisture
        self.min_moisture = min_moisture
        self.initial_moisture = initial_moisture
        self.pot_area = pot_area

        #Calibration (from soil_moisture_experiment.py)
        self.moisture_ref = moisture_ref
        self.cal_slope = cal_slope
        self.drain_slope = drain_slope
        self.drain_intercept = drain_intercept
        self.water_capacity = -drain_intercept / drain_slope
        # V is relative to the calibration reference (soil was not fully dry there),
        # so drier-than-reference states are negative V, down to reading min_moisture:
        self.water_volume_min = (min_moisture - moisture_ref) / cal_slope

        #Dynamic simulation states
        self.moisture = initial_moisture
        self.step_water_in = 0.0
        self.step_water_drained = 0.0
        self.water_volume = self.calculate_water_volume_from_moisture()

    def update_moisture(self):
        """
        Adds the incoming step water to the pot: the part the soil can retain
        (linear drainage model from the experiment) stays, the rest drains and
        is stored in step_water_drained. Then recalculates moisture.
        :return: moisture level
        """
        added = self.step_water_in
        retained = self.drain_slope * self.water_volume + self.drain_intercept
        retained = min(max(retained, 0.0), added)  # cannot retain more than was added
        self.step_water_drained = added - retained
        self.water_volume = self.water_volume + retained
        self.step_water_in = 0.0
        self.calculate_moisture_from_water_volume()

    def calculate_moisture_from_water_volume(self):
        """
        Maps retained water volume [L] to sensor moisture reading,
        linear calibration from the watering experiment.
        """
        self.water_volume = max(self.water_volume_min, min(self.water_volume, self.water_capacity))
        self.moisture = self.moisture_ref + self.cal_slope * self.water_volume
        return self.moisture


    def calculate_water_volume_from_moisture(self):
        """
        Inverse mapping: sensor moisture reading to retained water volume [L].
        """
        self.water_volume = (self.moisture - self.moisture_ref) / self.cal_slope
        self.water_volume = max(self.water_volume_min, min(self.water_volume, self.water_capacity))
        return self.water_volume
