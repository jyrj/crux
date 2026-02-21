"""Gray code encoding verification for multi-bit CDC crossings.

Verifies that a multi-bit signal crossing clock domains through a synchronizer
uses gray encoding (only 1 bit changes per transition). Detection is structural:
looks for the XOR-shift pattern `gray = binary ^ (binary >> 1)` in the netlist.

Yosys folds constant shifts into wiring: the $xor cell's A input contains
[bit0, bit1, ..., bitN] and B input contains [bit1, bit2, ..., bitN, "0"].
There is no separate $shr cell.
"""

from __future__ import annotations

from .netlist import Netlist, FlipFlop, is_dff_type


def is_gray_encoded(netlist: Netlist, sync_stage1: FlipFlop) -> bool:
    """Check if the D-input of a synchronizer's first stage is gray-encoded.

    Returns True if the structural pattern matches binary-to-gray conversion:
      gray[i] = binary[i] XOR binary[i+1]  (for i < MSB)
      gray[MSB] = binary[MSB]               (MSB copied directly)

    The pattern in Yosys RTLIL: a $xor cell where input A has bits from one
    register and input B has the same bits shifted by 1 position (constant
    shift folded into wiring).
    """
    d_bits = sync_stage1.d_bits
    if len(d_bits) < 2:
        return False  # Single-bit doesn't need gray encoding

    # All D bits should be driven by the same $xor cell's Y output
    xor_cell_name = None
    xor_cell = None

    for d_bit in d_bits:
        if not isinstance(d_bit, int):
            return False
        if d_bit not in netlist.driver_index:
            return False

        cell_name, port_name = netlist.driver_index[d_bit]
        cell_data = netlist.cells.get(cell_name, {})

        if cell_data.get("type") == "$xor":
            if xor_cell_name is None:
                xor_cell_name = cell_name
                xor_cell = cell_data
            elif cell_name != xor_cell_name:
                return False  # Different XOR cells - not a single gray conversion
        elif is_dff_type(cell_data.get("type", "")):
            # MSB case: gray[MSB] = binary[MSB], direct FF-to-FF connection
            # This is acceptable for the MSB bit
            pass
        else:
            return False  # Unknown logic in path

    if xor_cell is None:
        return False  # No XOR found at all

    # Verify the XOR pattern: A[i] and B[i] should be from the same source
    # register, with B being A shifted right by 1
    conn = xor_cell.get("connections", {})
    a_bits = conn.get("A", [])
    b_bits = conn.get("B", [])
    y_bits = conn.get("Y", [])

    if len(a_bits) != len(b_bits) or len(a_bits) != len(y_bits):
        return False

    width = len(a_bits)
    if width < 2:
        return False

    # Check the shift-by-1 pattern:
    # B[i] should equal A[i+1] for i < width-1
    # B[width-1] should be constant "0" (or "1" for some encodings)
    for i in range(width - 1):
        if b_bits[i] != a_bits[i + 1]:
            return False

    # MSB of B should be constant 0
    if b_bits[width - 1] not in ("0", 0):
        return False

    # Verify A bits come from a single source register (all driven by same FF)
    source_ff_name = None
    for a_bit in a_bits:
        if not isinstance(a_bit, int):
            return False
        if a_bit not in netlist.driver_index:
            return False
        cell_name, port_name = netlist.driver_index[a_bit]
        cell_data = netlist.cells.get(cell_name, {})
        if not is_dff_type(cell_data.get("type", "")):
            return False  # Source must be a register
        if source_ff_name is None:
            source_ff_name = cell_name
        elif cell_name != source_ff_name:
            return False  # Multiple source FFs - not a single counter

    return True
