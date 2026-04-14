"""Gray code encoding verification for multi-bit CDC crossings.

Detects the XOR-shift pattern `gray = binary ^ (binary >> 1)` in Yosys
netlists. Yosys folds constant shifts into wiring (no $shr cell).

Limitation: detection relies on Yosys preserving the $xor cell structure
after `proc; opt -fast`. If Yosys optimizes into LUTs or folds the XOR
differently, detection will fail (returning False = conservative, not
a false "safe"). Run with `opt -fast` not `opt -full` to preserve structure.
"""

from __future__ import annotations

from .netlist import Netlist, FlipFlop, is_dff_type


def is_gray_encoded(netlist: Netlist, sync_stage1: FlipFlop) -> bool:
    """Check if sync stage1's D-input has gray encoding (XOR-shift pattern).

    Returns True only if the specific structural pattern is found.
    Returns False conservatively if the pattern is absent or unrecognizable
    (may cause false MULTI_BIT_CDC violations — safer than false negatives).
    """
    d_bits = sync_stage1.d_bits
    if len(d_bits) < 2:
        return False

    # Find the XOR cell driving the D-inputs
    xor_cell_name = None
    xor_cell = None
    has_direct_ff = False

    for d_bit in d_bits:
        if not isinstance(d_bit, int) or d_bit not in netlist.driver_index:
            return False

        cell_name, port_name = netlist.driver_index[d_bit]
        cell_data = netlist.cells.get(cell_name, {})
        cell_type = cell_data.get("type", "")

        if cell_type == "$xor":
            if xor_cell_name is None:
                xor_cell_name = cell_name
                xor_cell = cell_data
            elif cell_name != xor_cell_name:
                return False
        elif is_dff_type(cell_type):
            has_direct_ff = True  # MSB directly from FF (valid)
        else:
            return False

    if xor_cell is None:
        return False

    return _verify_xor_shift(netlist, xor_cell)


def _verify_xor_shift(netlist: Netlist, xor_cell: dict) -> bool:
    """Verify XOR cell implements binary-to-gray shift pattern.

    Pattern: A = [bit0, bit1, ..., bitN], B = [bit1, bit2, ..., bitN, "0"]
    This is `binary ^ (binary >> 1)` with the shift folded into wiring.
    """
    conn = xor_cell.get("connections", {})
    a_bits = conn.get("A", [])
    b_bits = conn.get("B", [])

    if len(a_bits) != len(b_bits) or len(a_bits) < 2:
        return False

    width = len(a_bits)

    # Check shift-by-1: B[i] == A[i+1] for i < width-1
    for i in range(width - 1):
        if b_bits[i] != a_bits[i + 1]:
            return False

    # MSB of B must be constant 0
    if b_bits[width - 1] not in ("0", 0):
        return False

    # A bits must come from a single source register
    source_ff = None
    for a_bit in a_bits:
        if not isinstance(a_bit, int) or a_bit not in netlist.driver_index:
            return False
        cell_name, _ = netlist.driver_index[a_bit]
        cell_data = netlist.cells.get(cell_name, {})
        if not is_dff_type(cell_data.get("type", "")):
            return False
        if source_ff is None:
            source_ff = cell_name
        elif cell_name != source_ff:
            return False

    return True
