"""Parse Yosys JSON netlist into an internal model for CDC analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# All Yosys DFF cell types (generic and tech-mapped)
DFF_TYPES = frozenset({
    "$dff", "$dffe", "$adff", "$adffe", "$sdff", "$sdffe", "$sdffce", "$dffsr",
})

# Tech-mapped DFF pattern prefix
DFF_TECHMAP_PREFIX = "$_DFF_"

# Ports that carry clock signals on DFF cells
CLK_PORT_NAMES = ("CLK", "C")

# Ports that carry data
D_PORT_NAMES = ("D",)
Q_PORT_NAMES = ("Q",)

# Reset ports
RESET_PORT_NAMES = ("ARST", "SRST", "R", "S")

# Async reset cell types (as opposed to sync reset $sdff/$sdffe)
ASYNC_RESET_TYPES = frozenset({"$adff", "$adffe", "$dffsr"})

# MUX cell types (used for reconvergence classification)
MUX_TYPES = frozenset({"$mux", "$pmux"})


def is_dff_type(cell_type: str) -> bool:
    """Check if a cell type is a flip-flop."""
    return cell_type in DFF_TYPES or cell_type.startswith(DFF_TECHMAP_PREFIX)


def _get_port(connections: dict, names: tuple[str, ...]) -> list:
    """Get the first matching port connection from a list of possible names."""
    for name in names:
        if name in connections:
            return connections[name]
    return []


@dataclass
class FlipFlop:
    """Represents a flip-flop cell in the netlist."""
    name: str
    cell_type: str
    clock_net: int          # Net bit ID driving CLK
    clock_polarity: int     # 1 = posedge, 0 = negedge
    d_bits: list[int]       # Net bit IDs for D input
    q_bits: list[int]       # Net bit IDs for Q output
    reset_net: int | None   # Net bit ID for async/sync reset
    src: str                # Source file location from Yosys attributes


@dataclass
class NetInfo:
    """Human-readable info about a net bit."""
    name: str
    src: str
    bit_index: int          # Index within the bus (0 for single-bit)


@dataclass
class Netlist:
    """Parsed Yosys JSON netlist."""
    module_name: str
    flip_flops: dict[str, FlipFlop]         # cell_name -> FlipFlop
    cells: dict[str, dict[str, Any]]        # cell_name -> raw cell data
    ports: dict[str, dict[str, Any]]        # port_name -> port data
    netnames: dict[int, NetInfo]            # net_bit_id -> NetInfo
    port_bits: dict[int, str]               # net_bit_id -> port name (for inputs)
    driver_index: dict[int, tuple[str, str]]  # net_bit -> (cell_name, port_name)
    fanout_index: dict[int, list[tuple[str, str]]]  # net_bit -> [(cell_name, port_name)]

    @classmethod
    def from_json(cls, json_path: str | Path) -> Netlist:
        """Load and parse a Yosys JSON netlist."""
        with open(json_path) as f:
            data = json.load(f)

        modules = data.get("modules", {})
        if not modules:
            raise ValueError("No modules found in JSON netlist")

        # Use the first (and after flatten, only) module
        module_name = next(iter(modules))
        module = modules[module_name]

        return cls._parse_module(module_name, module)

    @classmethod
    def _parse_module(cls, module_name: str, module: dict) -> Netlist:
        cells = module.get("cells", {})
        ports = module.get("ports", {})
        raw_netnames = module.get("netnames", {})

        # Build net name index: bit_id -> NetInfo
        netnames: dict[int, NetInfo] = {}
        for name, info in raw_netnames.items():
            src = info.get("attributes", {}).get("src", "")
            for idx, bit in enumerate(info["bits"]):
                if isinstance(bit, int):
                    # Prefer non-hidden names, but don't overwrite with hidden
                    if bit not in netnames or not info.get("hide_name", 0):
                        netnames[bit] = NetInfo(name=name, src=src, bit_index=idx)

        # Build port bit index: which bits are module inputs
        port_bits: dict[int, str] = {}
        for port_name, port_data in ports.items():
            if port_data["direction"] == "input":
                for bit in port_data["bits"]:
                    if isinstance(bit, int):
                        port_bits[bit] = port_name

        # Parse flip-flops
        flip_flops: dict[str, FlipFlop] = {}
        for cell_name, cell_data in cells.items():
            if is_dff_type(cell_data["type"]):
                ff = cls._parse_ff(cell_name, cell_data)
                if ff is not None:
                    flip_flops[cell_name] = ff

        # Build driver index: for each net bit, which cell output drives it?
        driver_index: dict[int, tuple[str, str]] = {}
        for cell_name, cell_data in cells.items():
            pd = cell_data.get("port_directions", {})
            conn = cell_data.get("connections", {})
            for port_name, direction in pd.items():
                if direction == "output":
                    for bit in conn.get(port_name, []):
                        if isinstance(bit, int):
                            driver_index[bit] = (cell_name, port_name)

        # Build fanout index: for each net bit, who reads it?
        fanout_index: dict[int, list[tuple[str, str]]] = {}
        for cell_name, cell_data in cells.items():
            pd = cell_data.get("port_directions", {})
            conn = cell_data.get("connections", {})
            for port_name, direction in pd.items():
                if direction == "input":
                    for bit in conn.get(port_name, []):
                        if isinstance(bit, int):
                            fanout_index.setdefault(bit, []).append(
                                (cell_name, port_name)
                            )

        return cls(
            module_name=module_name,
            flip_flops=flip_flops,
            cells=cells,
            ports=ports,
            netnames=netnames,
            port_bits=port_bits,
            driver_index=driver_index,
            fanout_index=fanout_index,
        )

    @classmethod
    def _parse_ff(cls, cell_name: str, cell_data: dict) -> FlipFlop | None:
        """Parse a DFF cell into a FlipFlop object."""
        conn = cell_data.get("connections", {})
        params = cell_data.get("parameters", {})

        # Get clock connection
        clk_bits = _get_port(conn, CLK_PORT_NAMES)
        if not clk_bits:
            return None
        clock_net = clk_bits[0]
        if not isinstance(clock_net, int):
            return None

        # Clock polarity (default posedge = 1)
        clk_pol_str = params.get("CLK_POLARITY", "1")
        clock_polarity = 1 if clk_pol_str.endswith("1") else 0

        # Data ports
        d_bits = [b for b in _get_port(conn, D_PORT_NAMES) if isinstance(b, int)]
        q_bits = [b for b in _get_port(conn, Q_PORT_NAMES) if isinstance(b, int)]

        # Reset (optional)
        reset_bits = _get_port(conn, RESET_PORT_NAMES)
        reset_net = reset_bits[0] if reset_bits and isinstance(reset_bits[0], int) else None

        src = cell_data.get("attributes", {}).get("src", "")

        return FlipFlop(
            name=cell_name,
            cell_type=cell_data["type"],
            clock_net=clock_net,
            clock_polarity=clock_polarity,
            d_bits=d_bits,
            q_bits=q_bits,
            reset_net=reset_net,
            src=src,
        )

    def get_net_name(self, bit_id: int) -> str:
        """Get human-readable name for a net bit."""
        if bit_id in self.netnames:
            info = self.netnames[bit_id]
            return info.name
        if bit_id in self.port_bits:
            return self.port_bits[bit_id]
        return f"net_{bit_id}"


def has_async_reset(ff: FlipFlop) -> bool:
    """Check if a flip-flop has an asynchronous reset.

    Async resets ($adff, $adffe, $dffsr) cause RDC concerns when crossing domains.
    Sync resets ($sdff, $sdffe) are sampled on clock edge - no metastability risk.
    """
    if ff.reset_net is None:
        return False
    if ff.cell_type in ASYNC_RESET_TYPES:
        return True
    # Tech-mapped: $_DFF_PP0_ etc. - 3+ chars after $_DFF_ means has reset (always async)
    if ff.cell_type.startswith(DFF_TECHMAP_PREFIX):
        suffix = ff.cell_type[len(DFF_TECHMAP_PREFIX):]
        return len(suffix) >= 3
    return False
