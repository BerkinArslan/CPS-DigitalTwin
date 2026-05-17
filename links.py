"""

Includes object classes for link-type objects

"""

class Link:
    """
    Link object includes global link parameters
    """
    def __init__(self,
                 name: str,
                 start_node: str,
                 end_node: str,
                 length: float,):
        """
        Creates a new link with global parameters
        :param name: Name of the link.
        :param start_node: Name of the node where the link starts.
        :param end_node: Name of the node where the link ends.
        """
        self.name = name
        self.start_node = start_node
        self.end_node = end_node
        self.length = length

class Pipe(Link):
    """
    Represents a pipe in system
    """
    def __init__(self,
                 name: str,
                 start_node: str,
                 end_node: str,
                 length: float,
                 diameter: float,
                 roughness: float,):
        """
        Creates a new pipe with parameters
        :param name: Name of the pipe.
        :param start_node: Name of the node where the pipe starts.
        :param end_node: Name of the node where the pipe ends.
        :param length: Length of the pipe.
        """
        super().__init__(name, start_node, end_node, length)
        #Static states
        self.diameter = diameter
        self.roughness = roughness

        # TODO:
        #  add water flow to nodes and get water flow from relationship of the nodes
        #Dynamic simulation states
        self.water_flow = None



class Pump(Link):
    """
    Represents a link with pump system
    """
    def __init__(self,
                 name: str,
                 start_node: str,
                 end_node: str,
                 length: float,
                 diameter: float,
                 roughness: float,
                 power: float,):
        """
        Creates a new pump with parameters
        :param name: Name of the pump.
        :param start_node: Name of the node where the pump starts.
        :param end_node: Name of the node where the pump ends.
        :param length: Length of the pump.
        :param power: Power of the pump.
        """
        super().__init__(name, start_node, end_node, length)
        #Static states
        self.diameter = diameter
        self.roughness = roughness
        self.power = power

        # TODO: add waterflow to the links from edges adjacent to
        #  To do put the added flow we need to know the actuator data that we are gonna get
        #Dynamic simulation states
        self.water_flow = None
        self.added_flow = None