import platform
from cpuinfo import cpuinfo


class NodeInfo:
    def __init__(self, cpu, ram):
        self.cpu = cpu
        self.ram = ram

    def serialize(self):
        return {'cpu': self.cpu, 'ram': self.ram}


def get_node_info_for_current_machine():
    try:
        info = cpuinfo.get_cpu_info()
        # key was renamed to 'brand_raw' in py-cpuinfo 6.0
        cpu = info.get('brand_raw') or info.get('brand') or platform.machine()
    except Exception:
        cpu = platform.machine()
    return NodeInfo(cpu, '4 GB')


def create_node_info(json):
    return NodeInfo(json['cpu'], json['ram'])
