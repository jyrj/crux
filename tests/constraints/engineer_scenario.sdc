create_clock -name clk_sys -period 10.0  [get_ports clk_sys]
create_clock -name clk_per -period 40.0  [get_ports clk_per]
create_clock -name clk_dma -period 5.0   [get_ports clk_dma]

set_clock_groups -asynchronous \
    -group {clk_sys} \
    -group {clk_per} \
    -group {clk_dma}
