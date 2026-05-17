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
                 initial_moisture: float,):
        """
        Creates a new pot object
        :param name: Name of the pot
        :param coordinates: Coordinates of the pot
        :param elevation: Elevation of the pot from reference point (eg; ground)
        :param soil_volume: Soil volume of the pot
        :param max_moisture: Maximum possible moisture level of the pot
        :param min_moisture: Minimum possible moisture level of the pot
        :param initial_moisture: Moisture level at initiation
        """
        super().__init__(name, coordinates, elevation)
        #Static states
        self.soil_volume = soil_volume
        self.max_moisture = max_moisture
        self.min_moisture = min_moisture
        self.initial_moisture = initial_moisture

        #Dynamic simulation states
        self.moisture = initial_moisture

    # TODO:
    #  Import implemented mathematical model and use it in this method
    def update_moisture(self, water_flow):
        """
        Updates the moisture level of the pot according to mathematical model
        :param water_flow: input water flow (rain or irrigation)
        :return:
        """
        return

