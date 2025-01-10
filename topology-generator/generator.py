import argparse
from ipaddress import IPv4Interface, IPv4Network
from typing import Dict, List
from ruamel.yaml import YAML
import json

class NetworkPool:
    def __init__(self, network: IPv4Network, new_prefix: int=28) -> None:
        self.free_networks = list(network.subnets(new_prefix=new_prefix))

    def gen_network(self) -> IPv4Network:
        return self.free_networks.pop(0)


class Node:
    def __init__(self, device: str, component: str, include_routes: bool=True) -> None:
        self.device = device
        self.component = component
        self.interfaces = []
        self.include_routes = include_routes

    def add_interface(self, interface: 'Interface') -> str:
        id = f'i{len(self.interfaces)}'
        self.interfaces.append(interface)
        return id

    def get_id(self) -> str:
        raise NotImplementedError()

    def get_short(self) -> str:
        raise NotImplementedError()

    def dump(self) -> Dict:
        result = {
            'id': self.get_id(),
            'device': self.device,
            'component': self.component,
            'interfaces': [interface.dump() for interface in self.interfaces]
        }

        if self.include_routes:
            result['routes'] = [
                {
                    'network': str(network),
                    'gateway': str(gw_interface.get_ip().ip),
                    'metric': dist
                }
                for network, (interface, gw_interface, dist) in self.get_simplified_routes().items()
                if interface != gw_interface
            ]

        return result

    def get_ips(self) -> Dict:
        result = {
            'id': self.get_id(),
            'interfaces': [str(interface.get_ip().ip) for interface in self.interfaces]
        }

        return result

    def get_routes(self) -> Dict:
        routes = {}
        for interface in self.interfaces:
            for channel, gw_interface, dist in interface.channel.routes:
                if channel not in routes.keys() or routes[channel][2] > dist:
                    routes[channel] = interface, gw_interface, dist
        return routes

    def get_simplified_routes(self) -> Dict:
        def custom(tuple):
            return tuple[0]

        routes = [(channel.network, v) for channel, v in self.get_routes().items()]
        routes.sort(key=custom)

        result = []
        for entry in routes:
            result.append(entry)
            while len(result) > 1 and result[-1][0].supernet() == result[-2][0].supernet() and result[-1][1][1] == result[-2][1][1]:
                a = result.pop()
                b = result.pop()
                result.append((a[0].supernet(), a[1]))

        return {
            network: v for network, v in result
        }

    def get_additional_networks(self) -> List[IPv4Network]:
        return []


class Channel:
    def __init__(self, id: str, network: IPv4Network, delay: int):
        self.id = id
        self.network = network
        self.delay = delay
        self.interfaces = []
        self.routes = []

    @staticmethod
    def auto(node_a: Node, node_b: Node, network: IPv4Network, delay: int=0, id_a: str=None, id_b: str=None):
        channel = Channel(f'c_{node_a.get_short()}_{node_b.get_short()}', network, delay)
        Interface(node_a, channel, id=id_a)
        Interface(node_b, channel, id=id_b)
        return channel

    def add_interface(self, interface: 'Interface'):
        offset = len(self.interfaces)
        self.interfaces.append(interface)
        return offset

    def dump(self):
        result = {
            'id': self.id
        }

        if self.delay:
            result['delay'] = f'{self.delay}us'

        return result

    def distribute_route(self):
        known = set()
        queue = []

        known.add(self)
        queue.append((self, 0))
        while len(queue):
            cur_channel, cur_dist = queue.pop(0)
            for in_interface in cur_channel.interfaces:
                for out_interface in in_interface.node.interfaces:
                    next_channel = out_interface.channel
                    if not next_channel in known:
                        known.add(next_channel)
                        queue.append((next_channel, cur_dist + 1))

                        next_channel.routes.append((self, out_interface, cur_dist + 1))


class Interface:
    def __init__(self, node: Node, channel: Channel, id: str=None):
        self.node = node
        if id is not None:
            self.id = id
            node.add_interface(self)
        else:
            self.id = node.add_interface(self)
        self.channel = channel
        self.offset = channel.add_interface(self)

    def get_ip(self) -> IPv4Interface:
        return IPv4Interface((self.channel.network[self.offset + 1], self.channel.network.prefixlen))

    def dump(self) -> Dict:
        return {
            'id': self.id,
            'channel': self.channel.id,
            'ip': self.get_ip().with_prefixlen
        }


class NodeBackbone(Node):
    def __init__(self, num: int, subnum: int) -> None:
        super().__init__('router', 'simple-router') 
        self.num = num
        self.subnum = subnum

    def get_id(self) -> str:
        return f'backbone{self.num}.{self.subnum}'

    def get_short(self) -> str:
        return f'bb{self.num}.{self.subnum}'


class NodeAggregation(Node):
    def __init__(self, num: int, subnum: int) -> None:
        super().__init__('router', 'simple-router')
        self.num = num
        self.subnum = subnum

    def get_id(self) -> str:
        return f'aggregation{self.num}.{self.subnum}'

    def get_short(self) -> str:
        return f'agg{self.num}.{self.subnum}'


class NodeAccess(Node):
    def __init__(self, num: int) -> None:
        super().__init__('router', 'simple-router')
        self.num = num

    def get_id(self) -> str:
        return f'access{self.num}'

    def get_short(self) -> str:
        return f'acc{self.num}'


class NodeUW(Node):
    def __init__(self, num: int) -> None:
        super().__init__('container', 'simple-uw')
        self.num = num

    def get_id(self):
        return f'uw{self.num}'

    def get_short(self):
        return f'uw{self.num}'


class NodeExternal(Node):
    def __init__(self, id: str, additional_networks: List[IPv4Network]) -> None:
        super().__init__('host', 'host', include_routes=False)
        self.id = id
        self.additional_networks = additional_networks

    def get_id(self) -> str:
        return self.id

    def get_short(self) -> str:
        return self.id

    def get_additional_networks(self) -> List[IPv4Network]:
        result = super().get_additional_networks()
        result.extend(self.additional_networks)
        return result


class Topology:
    backbone_num = 0
    backbone_nodes: List[NodeBackbone] = []

    aggregation_num = 0
    aggregation_nodes: List[NodeAggregation] = []

    access_num = 0
    access_nodes: List[NodeAccess] = []

    uw_num = 0
    uw_nodes: List[NodeUW] = []

    external_prefix = 'ext'
    external_num = 0
    external_nodes: List[NodeExternal] = []

    def __init__(self) -> None:
        pass

    def add_backbone(self, length: int, network_pool: NetworkPool, delay: int) -> List[List[Node]]:
        nodes = []

        # Create pairs of backbone nodes (and an internal channel for each pair)
        for i in range(length):
            cur_num = self.backbone_num + i
            inner_nodes = [
                NodeBackbone(cur_num, j) for j in range(2)
            ]
            channel = Channel.auto(inner_nodes[0], inner_nodes[1], network_pool.gen_network())
            nodes.append(inner_nodes)

        # Backbone node to next backbone node
        for i in range(length):
            cur_node = nodes[i][1]
            next_node = nodes[(i + 1) % length][0]
            channel = Channel.auto(cur_node, next_node, network_pool.gen_network(), delay=delay)

        self.backbone_num += length
        self.backbone_nodes.extend(nodes)

        return nodes

    def add_aggregation(self, uplink_a: Node, uplink_b: Node, length: int, network_pool: NetworkPool, delay: int) -> List[List[Node]]:
        nodes = []

        # Create pairs of aggregation nodes (and an internal channel for each pair)
        for i in range(length):
            cur_num = self.aggregation_num + i
            inner_nodes = [
                NodeAggregation(cur_num, j) for j in range(2)
            ]
            channel = Channel.auto(inner_nodes[0], inner_nodes[1], network_pool.gen_network())
            nodes.append(inner_nodes)

        # Backbone node a to loop start node
        if length:
            next_node = nodes[0][0]
            channel = Channel.auto(uplink_a, next_node, network_pool.gen_network(), delay=delay)

        # Loop node to next loop node
        for i in range(length - 1):
            cur_node = nodes[i][1]
            next_node = nodes[i + 1][0]
            channel = Channel.auto(cur_node, next_node, network_pool.gen_network(), delay=delay)

        # Loop end node to backbone node b
        if length:
            cur_node = nodes[length - 1][1]
            channel = Channel.auto(cur_node, uplink_b, network_pool.gen_network(), delay=delay)

        self.aggregation_num += length
        self.aggregation_nodes.extend(nodes)

        return nodes

    def add_access(self, uplink: Node, length: int, network_pool: NetworkPool, delay: int) -> List[Node]:
        nodes = []

        for i in range(length):
            cur_num = self.access_num + i
            node = NodeAccess(cur_num)
            nodes.append(node)

        if length > 0:
            channel = Channel.auto(uplink, nodes[0], network_pool.gen_network(), delay=delay)
        for i in range(1, length):
            channel = Channel.auto(nodes[i - 1], nodes[i], network_pool.gen_network(), delay=delay)

        self.access_num += length
        self.access_nodes.extend(nodes)

        return nodes

    def add_uw(self, uplinks: List[Node], network_pool: NetworkPool) -> NodeUW:
        node = NodeUW(self.uw_num)

        # Each uplink to UW node
        for uplink in uplinks:
            channel = Channel.auto(uplink, node, network_pool.gen_network())

        self.uw_num += 1
        self.uw_nodes.append(node)

        return node

    def add_external(self, uplink: Node, network: IPv4Network, id: str) -> NodeExternal:
        node = NodeExternal(f'{self.external_prefix}{self.external_num}', [])

        channel = Channel.auto(uplink, node, network, id_b=id)

        self.external_num += 1
        self.external_nodes.append(node)

        return node

    def get_nodes(self) -> List[Node]:
        # Create flattened list of all nodes
        nodes = []
        for node in self.backbone_nodes + self.aggregation_nodes:
            nodes.extend(node)
        nodes.extend(self.access_nodes)
        nodes.extend(self.uw_nodes)
        nodes.extend(self.external_nodes)
        return nodes

    def get_uw_nodes(self) ->List[Node]:
        nodes = []
        nodes.extend(self.uw_nodes)
        return nodes

    def get_channels(self) -> List[Channel]:
        # Create flattened list of all channels
        channels = set()
        for node in self.get_nodes():
            for interface in node.interfaces:
                if not interface.channel in channels:
                    channels.add(interface.channel)
        return list(channels)

    def dump(self) -> Dict:
        return {
            'version': '1.0',
            'nodes': [node.dump() for node in self.get_nodes()],
            'channels': [channel.dump() for channel in self.get_channels()]
        }

    def distribute_routes(self) -> None:
        for channel in self.get_channels():
            channel.distribute_route()


def gen_topology_small() -> Topology:
    topology = Topology()

    topology.add_backbone(10)

    topology.add_aggregation(topology.backbone_nodes[0][1], topology.backbone_nodes[1][0], 2)
    topology.add_aggregation(topology.backbone_nodes[2][1], topology.backbone_nodes[3][0], 2)
    topology.add_aggregation(topology.backbone_nodes[4][1], topology.backbone_nodes[5][0], 3)
    topology.add_aggregation(topology.backbone_nodes[6][1], topology.backbone_nodes[7][0], 3)
    topology.add_aggregation(topology.backbone_nodes[8][1], topology.backbone_nodes[9][0], 3)

    # Create one station for each backbone or aggregation node
    for uplinks in topology.backbone_nodes + topology.aggregation_nodes:
        topology.add_uw(uplinks)

    topology.add_external(topology.backbone_nodes[0][0], IPv4Network('10.100.101.0/24'))
    topology.add_external(topology.backbone_nodes[0][1], IPv4Network('10.100.102.0/24'))

    return topology


def gen_topology(backbone_length: int, aggregation_length: int, access_length: int) -> Topology:
    topology = Topology()

    network_pool = backbone_pool = NetworkPool(IPv4Network('10.96.0.0/16'))

    backbone = topology.add_backbone(backbone_length, network_pool, 25)
    for i in range(backbone_length):
        topology.add_uw(backbone[i], network_pool)

        aggregation = topology.add_aggregation(backbone[i][1], backbone[(i + 1) % backbone_length][0], aggregation_length, network_pool, 150)
        for j in range(aggregation_length):
            topology.add_uw(aggregation[j], network_pool)

            access = topology.add_access(aggregation[j][0], access_length, network_pool, 100)
            for k in range(access_length):
                topology.add_uw([access[k]], network_pool)

    topology.add_external(topology.backbone_nodes[0][0], IPv4Network('10.100.101.0/24'), 'rettij.pc') 
    topology.add_external(topology.access_nodes[len(topology.access_nodes) // 2], IPv4Network('10.100.102.0/24'), 'rettij.rtu')

    return topology


def write_topology_file(topology, topology_file) -> None:
    with open(topology_file, 'w') as file:
        yaml = YAML()
        yaml.dump(topology.dump(), file)

def write_uw_ip_file(topology, uw_ip_file) -> None:
    output = []
    for node_object in [topology.get_uw_nodes()]:
        for node in node_object:
            output.append(node.get_ips())
    with open(uw_ip_file, 'w') as file:
        json.dump(output, file, ensure_ascii=False)
    file.close()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'distribution-system-topo',
        metavar='topology-file',
        help='Path of resulting topology file.'
    )
    parser.add_argument(
        'distribution-system-ips',
        metavar='uw-ip-file',
        help='Path of resulting UW IP file.' 
    )
    args = parser.parse_args()

    topology = gen_topology(20, 3, 3)
    topology.distribute_routes()
    write_topology_file(topology, args.topology_file)
    print([topology.get_uw_nodes()][0][0].dump())

    write_uw_ip_file(topology, args.uw_ip_file)

    return

    for node in [topology.get_nodes()[0]]:
        print(node.get_id())
        for route_k, route_v in node.get_simplified_routes().items():
            interface, gw_interface, dist = route_v
            if interface != gw_interface:
                print(route_k, 'via', gw_interface.get_ip().ip, 'dist', dist)


if __name__ == '__main__':
    main()
