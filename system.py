"""

This module includes class for the IrrigationSystem
IrrigationSystem is the sup-class that includes edges and links
This will also include global settings for simulation and simulation method

"""
from links import Pump, Pipe
from nodes import WaterTank, Pot, Node
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle, Polygon
from matplotlib.collections import PatchCollection


class IrrigationSystem:


    def __init__(self):
        self.nodes = {}
        self.links = {}


    def add_water_tank(self,
                        name: str,
                        coordinates: tuple[float, float],
                        elevation: float,
                        max_head: float,
                        min_head: float,
                        max_volume: float,
                        initial_volume: float):
        """
        Adds a WaterTank object to nodes in self.nodes.
        :param name: Name of the WaterTank object that is to be added.
        :param coordinates: x, y coordinates of water tank.
        :param elevation: Elevation of the water tank from global reference point (eg; ground)
        :param max_head: Maximum potential energy derived from the maximum top level of water.
        :param min_head: Minimum potential energy derived from the minimum top level of water.
        :param max_volume: Maximum water capacity of the water tank.
        :param initial_volume: Water volume in the water tank at the initial time.
        :return: None
        """
        water_tank = WaterTank(name = name,
                               coordinates = coordinates,
                               elevation = elevation,
                               max_head = max_head,
                               min_head = min_head,
                               max_volume = max_volume,
                               initial_volume = initial_volume)
        self.nodes[name] = water_tank


    def add_pot(self,
                name: str,
                coordinates: tuple[float, float],
                elevation: float,
                soil_volume: float,
                max_moisture: float,
                min_moisture: float,
                initial_moisture: float,
                ):
        """
        Adds a pot to the system nodes in self.nodes.
        :param name: Name of the pot
        :param coordinates: Coordinates of the pot
        :param elevation: Elevation of the pot from reference point (eg; ground)
        :param soil_volume: Soil volume of the pot
        :param max_moisture: Maximum possible moisture level of the pot
        :param min_moisture: Minimum possible moisture level of the pot
        :param initial_moisture: Moisture level at initiation
        """
        pot = Pot(name = name,
                  coordinates = coordinates,
                  elevation = elevation,
                  soil_volume = soil_volume,
                  max_moisture = max_moisture,
                  min_moisture = min_moisture,
                  initial_moisture = initial_moisture,)
        self.nodes[name] = pot


    def add_node(self,
                 name: str,
                 coordinates: tuple[float, float],
                 elevation: float, ):
        node = Node(name = name,
                    coordinates = coordinates,
                    elevation = elevation,)
        self.nodes[name] = node


    def get_node(self, name: str):
        """
        Gets the node object with the name.
        :param name: Name of the node object to be retrieved.
        :return: Node object with the name.
        """
        if name in self.nodes:
            return self.nodes[name]
        raise ValueError(f"Node with name {name} not found.")


    def add_pump(self,
                 name: str,
                 start_node: str,
                 end_node: str,
                 length: float,
                 diameter: float,
                 roughness: float,
                 power: float,):
        """
        Adds a Pump object to links in self.links.
        :param name: Name of the Pump object that is to be added.
        :param start_node: Name of the starting node of the link.
        :param end_node: Name of the ending node of the link.
        :param length: Length of the link.
        :param diameter: Diameter of the link.
        :param roughness: Roughness of the link.
        :param power: TBD
        :return:
        """
        pump = Pump(name = name,
                    start_node = start_node,
                    end_node = end_node,
                    length = length,
                    diameter = diameter,
                    roughness = roughness,
                    power = power,)
        self.links[name] = pump
        self.get_node(start_node).outgoing_links.append(pump)
        self.get_node(end_node).incoming_links.append(pump)

    def add_pipe(self,
                 name: str,
                 start_node: str,
                 end_node: str,
                 length: float,
                 diameter: float,
                 roughness: float,):
        """
        Adds a Pipe object to links in self.links.
        :param name: Name of the Pipe object that is to be added.
        :param start_node: Name of the starting node of the link.
        :param end_node: Name of the ending node of the link.
        :param length: Length of the link.
        :param diameter: Diameter of the link.
        :param roughness: Roughness of the link.
        :return:
        """
        pipe = Pipe(name = name,
                    start_node = start_node,
                    end_node = end_node,
                    length = length,
                    diameter = diameter,
                    roughness = roughness,)
        self.links[name] = pipe
        self.get_node(start_node).outgoing_links.append(pipe)
        self.get_node(end_node).incoming_links.append(pipe)

    def visualize_standard(self, size:float = 1, show_states:bool = True):
        """
        Visualizes the system in  simple plot
        :return:
        """
        fig, ax = plt.subplots()

        x_min, x_max = float('inf'), float('-inf')
        y_min, y_max = float('inf'), float('-inf')

        #add all of the nodes to the plot
        for node_name, node in self.nodes.items():
            x = node.coordinates[0]
            y = node.coordinates[1]

            x_min = min(x_min, x)
            x_max = max(x_max, x)
            y_min = min(y_min, y)
            y_max = max(y_max, y)

            #plot water tanks as blue box
            if isinstance(node, WaterTank):
                #plt.scatter(node.coordinates[0], node.coordinates[1], c='b')

                w, h = 1 * size, 1 * size
                tank = Rectangle(
                    (x - w/2, y - h/2),
                    w, h,
                    facecolor = 'royalblue',
                    edgecolor = 'black',
                    linewidth = 1*size,
                )
                ax.add_patch(tank)
                if show_states:
                    ax.text(x - 3 * size, y,
                        f'{node_name}\nVolume: {(node.volume/node.max_volume) * 100:.0f}%',
                        fontsize=3*size, bbox=dict(facecolor='white', edgecolor='black'))

            #plot pots looking like a pot in a plant
            elif isinstance(node, Pot):
                top_w = 1.0 * size
                bottom_w = 0.6 * size
                h = 1.0 * size

                points_pot = [
                    (x - top_w/2, y + bottom_w/2),
                    (x + top_w/2, y + bottom_w/2),
                    (x + bottom_w/2, y - bottom_w/2),
                    (x - bottom_w/2, y - bottom_w/2),
                ]

                pot_shape = Polygon(points_pot,
                                    facecolor = 'saddlebrown',
                                    edgecolor = 'black',
                                    linewidth = 1*size,)
                plant_w = 0.1 * size
                plant_h = 0.5 * size

                plant_shape = Rectangle(
                    (x - plant_w/2, y + plant_h/2),
                    plant_w, plant_h,
                    facecolor = 'green',
                )
                ax.add_patch(plant_shape)
                ax.add_patch(pot_shape)
                ax.text(x - 0.3*size, y - 0.1*size, f'{100 * (node.moisture - node.min_moisture) /\
                    (node.max_moisture + node.min_moisture):.0f}%',
                        fontsize=3*size, color='white')
            else:
                ax.scatter(x, y, c='black')

        #Now pot all of the links in the plot
        for link_name, link in self.links.items():
            starting_coordinates = self.get_node(link.start_node).coordinates
            ending_coordinates = self.get_node(link.end_node).coordinates
            X = [starting_coordinates[0], ending_coordinates[0]]
            Y = [starting_coordinates[1], ending_coordinates[1]]
            ax.plot(X, Y, label = link_name, linewidth = 0.5*size, c='gray', zorder = 0)


        ax.set_aspect('equal')
        ax.set_axis_off()
        padding = 1.5 * size
        ax.set_xlim(x_min - padding, x_max + padding)
        ax.set_ylim(y_min - padding, y_max + padding)
        plt.show()



if __name__ == '__main__':

    sys = IrrigationSystem()

    sys.add_water_tank(
        name = 'Tank1',
        coordinates = (0, 0),
        elevation = 0,
        max_head = 10,
        min_head = 0,
        max_volume = 100,
        initial_volume = 50,
    )

    sys.add_node(
        name = 'Node1',
        coordinates = (0, 20),
        elevation = 0,
    )

    sys.add_pump(
        name = 'Pipe1',
        start_node = 'Tank1',
        end_node = 'Node1',
        length = 20,
        diameter = 10,
        roughness = None,
        power=None
    )

    sys.add_node(
        name = 'Node2',
        coordinates = (0, 20),
        elevation = 10,
    )

    sys.add_pipe(
        name = 'Pipe2',
        start_node = 'Node1',
        end_node = 'Node2',
        length = 20,
        diameter = 10,
        roughness = None,
    )

    sys.add_pot(
        name = 'Pot1',
        coordinates = (10, 20),
        elevation = 10,
        soil_volume = 10,
        max_moisture = 100,
        min_moisture = 0,
        initial_moisture = 54,
    )

    sys.add_pipe(
        name='Pipe3',
        start_node='Node2',
        end_node='Pot1',
        length = 20,
        diameter = 10,
        roughness = None,
    )

    sys.add_node(
        name = 'Node4',
        coordinates = (20, 20),
        elevation = 10,
    )

    sys.add_pipe(
        name = 'Pipe4',
        start_node = 'Pot1',
        end_node = 'Node4',
        length = 20,
        diameter = 10,
        roughness = None,
    )

    sys.add_pot(
        name = 'Pot2',
        coordinates = (30, 20),
        elevation = 10,
        soil_volume = 10,
        max_moisture = 100,
        min_moisture = 0,
        initial_moisture = 74,
    )

    sys.add_pipe(
        name='Pipe5',
        start_node='Node4',
        end_node='Pot2',
        length = 20,
        diameter = 10,
        roughness = None,
    )

    sys.add_node(
        name = 'Node5',
        coordinates = (20, 10),
        elevation = 10,
    )

    sys.add_pipe(
        name='Pipe6',
        start_node='Node4',
        end_node='Node5',
        length = 20,
        diameter = 10,
        roughness = None,
    )

    sys.add_pot(
        name='Pot3',
        coordinates=(30, 10),
        elevation=10,
        soil_volume=10,
        max_moisture=100,
        min_moisture=0,
        initial_moisture=38,
    )

    sys.add_pipe(
        name='Pipe7',
        start_node='Node5',
        end_node='Pot3',
        length=20,
        diameter=10,
        roughness=None,
    )

    sys.add_pot(
        name='Pot4',
        coordinates=(20, 5),
        elevation=10,
        soil_volume=10,
        max_moisture=100,
        min_moisture=0,
        initial_moisture=67,
    )

    sys.add_pipe(
        name='Pipe8',
        start_node='Node5',
        end_node='Pot4',
        length=20,
        diameter=10,
        roughness=None,
    )

    sys.visualize_standard(size=3)

