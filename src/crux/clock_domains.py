"""Identify clock domains by grouping flip-flops that share the same clock net."""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from .netlist import Netlist, FlipFlop


@dataclass
class ClockDomain:
    """A group of flip-flops driven by the same clock signal."""
    clock_net: int
    clock_name: str
    polarity: int           # 1 = posedge, 0 = negedge
    flip_flops: list[FlipFlop]


def find_clock_domains(netlist: Netlist) -> dict[int, ClockDomain]:
    """Group all flip-flops by their clock net, returning clock_net -> ClockDomain."""
    groups: dict[int, list[FlipFlop]] = defaultdict(list)

    for ff in netlist.flip_flops.values():
        groups[ff.clock_net].append(ff)

    domains: dict[int, ClockDomain] = {}
    for clock_net, ffs in groups.items():
        clock_name = netlist.get_net_name(clock_net)
        polarity = ffs[0].clock_polarity  # All FFs on same net share polarity
        domains[clock_net] = ClockDomain(
            clock_net=clock_net,
            clock_name=clock_name,
            polarity=polarity,
            flip_flops=ffs,
        )

    return domains
