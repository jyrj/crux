# EarlGrey-style clock constraints
create_clock -name clk_main  -period 10.0  [get_ports clk_main_i]
create_clock -name clk_io    -period 41.67 [get_ports clk_io_i]
create_clock -name clk_usb   -period 20.83 [get_ports clk_usb_i]
create_clock -name clk_aon   -period 5000  [get_ports clk_aon_i]

# Generated clocks (derived from IO clock)
create_generated_clock -name clk_io_div2 \
    -source [get_ports clk_io_i] \
    -divide_by 2 \
    [get_pins clkmgr/clk_io_div2_o]

create_generated_clock -name clk_io_div4 \
    -source [get_ports clk_io_i] \
    -divide_by 4 \
    [get_pins clkmgr/clk_io_div4_o]

# Declare asynchronous clock relationships
# clk_main, clk_io, clk_usb, and clk_aon are all asynchronous to each other
set_clock_groups -asynchronous \
    -group {clk_main} \
    -group {clk_io clk_io_div2 clk_io_div4} \
    -group {clk_usb} \
    -group {clk_aon}

# False paths for quasi-static configuration registers
set_false_path -from [get_clocks clk_main] -to [get_clocks clk_aon]
