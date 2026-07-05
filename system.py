"""

This module includes class for the IrrigationSystem
IrrigationSystem is the sup-class that includes edges and links
This will also include global settings for simulation and simulation method

"""
import utils
from evapotranspiration import crop_evapotranspiration, reference_evapotranspiration, water_volume_loss_to_evaporation
from links import Pump, Pipe
from nodes import WaterTank, Pot, Node
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle, Polygon
from matplotlib.collections import PatchCollection
import numpy as np


#TODO:
# Change network solvers names and parameters.
# they take solve from tank to pump anf from pump to pot


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
                 power: float,
                 flow_rate: float,
                 activation_time: float | list):
        """
        Adds a Pump object to links in self.links.
        :param name: Name of the Pump object that is to be added.
        :param start_node: Name of the starting node of the link.
        :param end_node: Name of the ending node of the link.
        :param length: Length of the link.
        :param diameter: Diameter of the link.
        :param roughness: Roughness of the link.
        :param power: TBD
        :param flow_rate: TBD
        :param activation_time: TBD
        :return:
        """
        pump = Pump(name = name,
                    start_node = start_node,
                    end_node = end_node,
                    length = length,
                    diameter = diameter,
                    roughness = roughness,
                    power = power,
                    flow_rate = flow_rate,
                    activation_time = activation_time)
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

    def visualize_standard(self, size:float = 1, show_states:bool = True, ax=None,
                           font_size: float = 9, shape_scale: float = 0.6):
        """
        Visualizes the system in  simple plot
        :param ax: optional matplotlib axis to draw on (for live animation).
                   If None, creates its own figure and blocks with plt.show().
        :param font_size: text size in points (independent of shape size)
        :param shape_scale: shrinks node shapes relative to coordinate distances
                            so neighbouring nodes don't touch (1.0 = old look)
        :return:
        """
        shape = size * shape_scale
        own_figure = ax is None
        if own_figure:
            fig, ax = plt.subplots()
        else:
            ax.clear()

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

                w, h = 1 * shape, 1 * shape
                tank = Rectangle(
                    (x - w/2, y - h/2),
                    w, h,
                    facecolor = 'royalblue',
                    edgecolor = 'black',
                    linewidth = 1*size,
                )
                ax.add_patch(tank)
                if show_states:
                    ax.text(x, y + h/2 + 0.15 * size,
                        f'{node_name}\nVolume: {(node.volume/node.max_volume) * 100:.0f}%',
                        fontsize=font_size, ha='center', va='bottom',
                        clip_on=True)
                        #bbox=dict(facecolor='white', edgecolor='black'))

            #plot pots looking like a pot in a plant
            elif isinstance(node, Pot):
                top_w = 1.0 * shape
                bottom_w = 0.6 * shape
                h = 1.0 * shape

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
                plant_w = 0.1 * shape
                plant_h = 0.5 * shape

                plant_shape = Rectangle(
                    (x - plant_w/2, y + plant_h/2),
                    plant_w, plant_h,
                    facecolor = 'green',
                )
                ax.add_patch(plant_shape)
                ax.add_patch(pot_shape)
                # ax.text(x - 0.3*size, y - 0.1*size, f'{100 * (node.moisture - node.min_moisture) /\
                #     (node.max_moisture + node.min_moisture):.0f}%',
                #         fontsize=3*size, color='white')
                if show_states:
                    ax.text(x, y + h/2 + 0.15 * size,
                            f'{node_name}\nMoisture: {100 * node.moisture:.0f}%',
                            fontsize=font_size, ha='center', va='bottom',
                            clip_on=True)
                            #bbox=dict(facecolor='white', edgecolor='black'))
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
        # padding scales with the network extent too, so labels of edge nodes
        # keep fitting inside the axes for wide networks at small `size`
        span = max(x_max - x_min, y_max - y_min, 1)
        padding = max(1.5 * size, 0.15 * span)
        ax.set_xlim(x_min - padding, x_max + padding)
        ax.set_ylim(y_min - padding, y_max + padding)
        if own_figure:
            plt.show()

    # def simulation_step(self, dt):
    #     """
    #     runs the simulation for one step with given dt
    #     :param dt: time difference to simualte
    #     :return: updates the states of the links and nodes
    #     """
    #
    #     for link in self.links.values():
    #         if isinstance(link, Pump):
    #             flow_volume = link.pump_it(0)
    #             link.start_node.volume = link.start_node.volume - flow_volume
    #             link.end_node.volume = link.end_node.volume + flow_volume

    # Conservation of mass
    def _node_inflows(self, pipe_volumes, node_names):
        """
        adds inflow of the pipe to end nodes and substract it from the outflows
        :param pipe_volumes: volume of flow for every pipe
        :param node_names: names nodes for which inflow is calculated
        :return:
        """
        inflows = {node_name: 0.0 for node_name in node_names}

        for pipe_name, volume in pipe_volumes.items():
            pipe = self.links[pipe_name]

            if pipe.end_node in inflows:
                inflows[pipe.end_node] += volume

            if pipe.start_node in inflows:
                inflows[pipe.start_node] -= volume

        return inflows
    #TODO:
    # this is redundant. delete this later and use negative inflow for outflow
    def _node_outflows(self, pipe_volumes, node_names):
        """
        adds inflow of the pipe to start nodes and substract it from the end_nodes
        :param pipe_volumes: flow for every pipe
        :param node_names: nodes for which outflow is calculated
        :return:
        """
        inflows = self._node_inflows(pipe_volumes, node_names)

        return {
            node_name: -volume
            for node_name, volume in inflows.items()
        }

    #Ax = b
    def _solve_resistance_network(self, tanks, pots, volume):
        """
        calculates the pipe flow volumes for a fixed total volume.

        real heads are unknown, so we pin relative heads at the boundaries
        just to set the flow direction and get the flow proportions:
        pot head = 0
        tank head = 1
        these fake values give the correct proportions but the wrong total,
        so at the end all flows are rescaled so the tanks together
        give out exactly `volume`

        for every unknown node (the nodes between tanks and pots) we write
        mass conservation: sum over neighbors of C * (h_i - h_j) = 0
        stacking one equation per unknown node gives the system Ax = b

        A is the coefficient table of these equations, row i = node i:
            A[i][i] = sum of conductances touching node i
            A[i][j] = -conductance between node i and unknown neighbor j
            (the minus is the second half of expanding C * (h_i - h_j))
        x is the heads of the unknown nodes (what the solver returns)
        b is the known part of the same equations: conductance to a
            boundary neighbor times that neighbor's pinned head

        in this function a constant head/energy is assumed
        for systems with big elevation difference this function
        may not give good results

        :param tanks: sources of water (head pinned to 1)
        :param pots: sinks of the graph (head pinned to 0)
        :param volume: total volume to distribute from tanks to pots
        :return: (pipe_volumes, tank_outflows, pot_inflows)
        """

        if volume <= 0:
            return {}, {}, {}

        tanks = list(tanks)
        pots = list(pots)

        boundary_head = {}

        for node_name in tanks:
            boundary_head[node_name] = 1

        for node_name in pots:
            boundary_head[node_name] = 0

        graph = utils.create_pipe_adjacency_dict(self.nodes, self.links)

        relevant_nodes = utils.relevant_nodes(graph, tanks, pots)

        if not relevant_nodes:
            return {}, {}, {}

        unknown_nodes = [
            node_name for node_name in relevant_nodes if node_name not in boundary_head
        ]

        node_index = {
            node_name: i for i, node_name in enumerate(unknown_nodes)
        }

        heads = dict(boundary_head) #creates a copy

        if unknown_nodes:
            A = np.zeros((len(unknown_nodes), len(unknown_nodes)))
            b = np.zeros(len(unknown_nodes))

            for node_name in unknown_nodes:
                i = node_index[node_name]

                for neighbor, _, conductance in graph[node_name]:
                    if neighbor not in relevant_nodes:
                        continue

                    A[i, i] = A[i, i] + conductance
                    if neighbor in boundary_head:
                        b[i] = b[i] + conductance * boundary_head[neighbor]
                    else:
                        j = node_index[neighbor]
                        A[i, j] = A[i, j] - conductance

            x = np.linalg.solve(A, b)

            for node_name, head in zip(unknown_nodes, x):
                heads[node_name] = head

        unit_pipe_volumes = {}

        pipes = {
            name: link
            for name, link in self.links.items()
            if isinstance(link, Pipe)
        }

        for pipe_name, pipe in pipes.items():
            if pipe.start_node not in relevant_nodes:
                continue

            if pipe.end_node not in relevant_nodes:
                continue
            #Q = C * delta_h for normed h
            conductance = utils.pipe_conductance(pipe)
            unit_pipe_volumes[pipe_name] = conductance * (heads[pipe.start_node] - heads[pipe.end_node])

        unit_source_out = self._node_outflows(unit_pipe_volumes, tanks)
        total_unit_source_out = sum(unit_source_out.values())

        if abs(total_unit_source_out) < 1e-12:
            return {}, {}, {}

        scale = volume / total_unit_source_out

        pipe_volumes = {
            pipe_name: scale * unit_volume
            for pipe_name, unit_volume in unit_pipe_volumes.items()
        }

        tank_outflows = self._node_outflows(pipe_volumes, tanks)
        pot_inflows = self._node_inflows(pipe_volumes, pots)

        return pipe_volumes, tank_outflows, pot_inflows
        ######

    def _solve_from_tanks_to_pump(self,
                                  tank_names,
                                  pump_start_node,
                                  requested_volume):
        """
        Calculates from which tank how much volume is going to specific pump
        :param tank_names: names of the tanks
        :param pump_start_node: name of the start node of the pump
        :param requested_volume: volume of flow from specifc pump
        :return:
        """

        tank_available = {
            tank_name: max(0.0, self.nodes[tank_name].volume)
            for tank_name in tank_names
        }

        if pump_start_node in tank_names:
            flow_volume = min(requested_volume, tank_available[pump_start_node])

            tank_out = {
                tank_name: 0.0
                for tank_name in tank_names
            }
            tank_out[pump_start_node] = flow_volume

            return flow_volume, {}, tank_out

        tanks_all_volume = sum([
            tank_available[tank_name]
            for tank_name in tank_names
        ])
        requested_volume = min(requested_volume, tanks_all_volume)

        tank_queue = [
            tank_name
            for tank_name in tank_names
            if tank_available[tank_name] > 0
        ]

        total_pipe_volumes = {}
        total_tank_out = {tank_name: 0.0 for tank_name in tank_names}

        while requested_volume > 1e-12 and len(tank_queue) > 0:
            pipe_volumes, tank_out, _ = self._solve_resistance_network(
                tanks=tank_queue,
                pots=[pump_start_node],
                volume=requested_volume,
            )

            empty_tanks = [
                tank_name
                for tank_name, volume in tank_out.items()
                if volume > tank_available[tank_name] + 1e-12
            ]

            if not empty_tanks:
                for pipe_name, volume in pipe_volumes.items():
                    total_pipe_volumes[pipe_name] = (
                        total_pipe_volumes.get(pipe_name, 0.0) + volume
                    )

                for tank_name, volume in tank_out.items():
                    total_tank_out[tank_name] = total_tank_out[tank_name] + volume

                requested_volume = 0.0
                break

            for tank_name in empty_tanks:
                capped_volume = tank_available[tank_name]

                if capped_volume > 1e-12:
                    capped_pipe_volumes, _, _ = self._solve_resistance_network(
                        tanks=[tank_name],
                        pots=[pump_start_node],
                        volume=capped_volume,
                    )

                    for pipe_name, volume in capped_pipe_volumes.items():
                        total_pipe_volumes[pipe_name] = (
                            total_pipe_volumes.get(pipe_name, 0.0) + volume
                        )

                    total_tank_out[tank_name] = total_tank_out[tank_name] + capped_volume
                    requested_volume = requested_volume - capped_volume

                tank_queue.remove(tank_name)
                tank_available[tank_name] = 0.0

        flow_volume = sum(total_tank_out.values())

        return flow_volume, total_pipe_volumes, total_tank_out

    def flow_simulation_step(self, schedule):
        """
        calls the necessary functions for simulation step and updates the states of the system
        :param schedule: rank of the order of simulation step
        :return:
        """
        pipe_volumes = {}

        for link in self.links.values():
            link.water_flow = 0.0

            if isinstance(link, Pump):
                link.added_flow = 0.0

        for node in self.nodes.values():
            if isinstance(node, Pot):
                node.step_water_in = 0.0

        tank_names = [
            node_name for node_name, node in self.nodes.items()
            if isinstance(node, WaterTank)
        ]

        pot_names = [
            node_name for node_name, node in self.nodes.items()
            if isinstance(node, Pot)
        ]

        pump_names = [
            link_name for link_name, link in self.links.items()
            if isinstance(link, Pump)
        ]

        for pump in [self.links[link_name] for link_name in pump_names]:

            requested_volume = pump.pump_it(schedule)

            actual_volume, upstream_pipe_volumes, tank_out = self._solve_from_tanks_to_pump(
                tank_names=tank_names,
                pump_start_node=pump.start_node,
                requested_volume=requested_volume,
            )

            if isinstance(self.nodes[pump.end_node], Pot):
                # Pump discharges directly into a pot: there is no downstream
                # pipe network to solve, the resistance network would mark the
                # pot as source AND sink and return nothing (water vanished).
                # Deliver the full pumped volume straight to that pot instead.
                downstream_pipe_volumes = {}
                pot_in = {pump.end_node: actual_volume}
            else:
                downstream_pipe_volumes, _, pot_in = self._solve_resistance_network(
                    tanks=[pump.end_node],
                    pots=pot_names,
                    volume=actual_volume,
                )

            for pipe_name, volume in upstream_pipe_volumes.items():
                pipe_volumes[pipe_name] = pipe_volumes.get(pipe_name, 0.0) + volume

            for pipe_name, volume in downstream_pipe_volumes.items():
                pipe_volumes[pipe_name] = pipe_volumes.get(pipe_name, 0.0) + volume

            pump.water_flow = pump.water_flow + actual_volume
            pump.added_flow = pump.added_flow + actual_volume

            for tank_name, volume in tank_out.items():
                self.nodes[tank_name].volume = (
                        self.nodes[tank_name].volume - volume)
                self.nodes[tank_name].update_head()

            for pot_name, volume in pot_in.items():
                self.nodes[pot_name].step_water_in = (
                    self.nodes[pot_name].step_water_in + volume
                )
                self.nodes[pot_name].update_moisture()
                print(f'{pot_name} water_in: {volume},'
                      f' total_water: {self.nodes[pot_name].water_volume}, '
                      f'moisture: {self.nodes[pot_name].moisture}, '
                      f'total_volume: {self.nodes[pot_name].soil_volume}')

        for pipe_name, volume in pipe_volumes.items():
            self.links[pipe_name].water_flow = volume

        return pipe_volumes

    def evapotranspiration_simulation_step(self,
                                           step_time_seconds: float,
                                           t_celcius: float,
                                           wind_speed: float,
                                           irradiation: float,
                                           soil_albedo: float,
                                           soil_absorption_ratio: float,
                                           crop_coefficient: float = 1,
                                           balcony_mc_coefficient: float = 0.75,
                                           evaporation_efficiency: float = 0.45,
                                           relative_humidity: float = 0.5,
                                           ):
        """
        Calcualtes the water loss in that time step for the given schedule
        Updates the moisture level and the water level in that pot
        :param schedule: if multiple steps re to be simulated the i-th step
        :return:
        """
        day = 60 * 60 * 24
        divider = step_time_seconds / day

        irradiation_work = irradiation * 24 * 3600 / 1e6
        plant_energy_absorption = (1- soil_absorption_ratio) * evaporation_efficiency * irradiation_work
        soil_energy_absorption = irradiation_work * (1 - soil_albedo) * soil_absorption_ratio
        pot_names = [pot_name for pot_name, pot in self.nodes.items() if isinstance(pot, Pot) ]
        for pot_name in pot_names:

            ref_et = reference_evapotranspiration(
                temp_c=t_celcius,
                wind_speed=wind_speed,
                soil_moisture=self.nodes[pot_name].moisture,
                min_soil_moisture=self.nodes[pot_name].min_moisture,
                max_soil_moisture=self.nodes[pot_name].max_moisture,
                canopy_energy_absorption=plant_energy_absorption,
                soil_energy_absorption=soil_energy_absorption,
                relative_humidity=relative_humidity,
            )

            pot_et = crop_evapotranspiration(ref_et,
                                             crop_coefficient=crop_coefficient,
                                             balcony_microclimate_correction=balcony_mc_coefficient)

            water_loss = water_volume_loss_to_evaporation(pot_et,
                                                          pot_area=self.nodes[pot_name].pot_area)

            water_loss = water_loss * divider
            print(f'water_loss: {water_loss}')

            self.nodes[pot_name].water_volume = self.nodes[pot_name].water_volume - water_loss
            self.nodes[pot_name].update_moisture()


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
        power=None,
        flow_rate = 0.5,
        activation_time=5,
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
        max_moisture = 1,
        min_moisture = 0,
        initial_moisture = 0.54,
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
        start_node = 'Node2',
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
        max_moisture = 1,
        min_moisture = 0,
        initial_moisture = 0.74,
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
        max_moisture=1,
        min_moisture=0,
        initial_moisture=0.38,
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
        max_moisture=1,
        min_moisture=0,
        initial_moisture=0.67,
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


    tank_volume_before = sys.nodes['Tank1'].volume

    pipe_volumes = sys.flow_simulation_step(schedule=0)

    tank_volume_after = sys.nodes['Tank1'].volume

    print("\nPipe volumes:")
    for pipe_name, volume in pipe_volumes.items():
        print(f"{pipe_name}: {volume:.8f}")

    print("\nPump:")
    print(f"Pipe1 water_flow: {sys.links['Pipe1'].water_flow:.8f}")
    print(f"Pipe1 added_flow: {sys.links['Pipe1'].added_flow:.8f}")

    print("\nTank:")
    print(f"Tank1 before: {tank_volume_before:.8f}")
    print(f"Tank1 after:  {tank_volume_after:.8f}")
    print(f"Tank1 lost:   {tank_volume_before - tank_volume_after:.8f}")

    print("\nPots:")
    for pot_name in ['Pot1', 'Pot2', 'Pot3', 'Pot4']:
        print(f"{pot_name} water in: {sys.nodes[pot_name].step_water_in:.8f}")

    total_pot_in = sum(
        sys.nodes[pot_name].step_water_in
        for pot_name in ['Pot1', 'Pot2', 'Pot3', 'Pot4']
    )

    sys.visualize_standard(size=3, show_states=True)
    for i in range(5):
        pipe_volumes = sys.flow_simulation_step(schedule=0)

        sys.visualize_standard(size=3, show_states=True)

        sys.evapotranspiration_simulation_step(
            step_time_seconds=24*60*60,
            t_celcius=22,
            wind_speed=5,
            irradiation=300,
            soil_albedo=0.2,
            soil_absorption_ratio=0.3,
        )

        sys.visualize_standard(size=3, show_states=True)

