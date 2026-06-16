"""
Useful functions
"""
from links import Pipe, Pump
from links import Link
from nodes import Node
import numpy as np

def pipe_conductance(pipe: Pipe):

    # if pipe.roughness is not None:
    #     roughness = max(pipe.roughness, 1e-12)
    # else:
    #     roughness = 1.0

    # conductance = (np.pi * pipe.diameter ** 4) / (pipe.length * roughness * 8)

    roughness = (np.pi * pipe.diameter ** 4) / (pipe.length *  8 * 1002 * 1e-6)
    return roughness

def create_pipe_adjacency_dict(nodes: dict, links: dict):

    graph = {node_name: [] for node_name in nodes}

    pipes = {
        name: link
        for name, link in links.items()
        if isinstance(link, Pipe)
    }

    for pipe_name, pipe in pipes.items():
        conductance = pipe_conductance(pipe)

        graph[pipe.start_node].append((pipe.end_node, pipe_name, conductance))
        graph[pipe.end_node].append((pipe.start_node, pipe_name, conductance))

    return graph

def relevant_nodes(graph: dict, tanks, pots):
    """
    Depth first search for all the nodes in-between a tank and a source
    To make sure that there is no pipes that lead to nowhere
    :param graph:
    :param tanks:
    :param pots:
    :return:
    """
    tanks = set(tanks)
    pots = set(pots)

    relevant_nodes = set()
    unvisited = set(graph.keys())

    while unvisited:
        start = unvisited.pop()
        component = {start}
        stack = [start]

        while stack:
            node_name = stack.pop()

            for neighbor, _, _ in graph[node_name]:
                if neighbor not in component:
                    component.add(neighbor)
                    stack.append(neighbor)
                    unvisited.remove(neighbor)

        if component & tanks and component & pots:
            relevant_nodes|= component

    return relevant_nodes


