# SDC constraints for realistic_soc test design

create_clock -name sys_clk -period 10.0  [get_ports sys_clk]
create_clock -name io_clk  -period 41.67 [get_ports io_clk]
create_clock -name aon_clk -period 5000  [get_ports aon_clk]

# All three clocks are asynchronous to each other
set_clock_groups -asynchronous \
    -group {sys_clk} \
    -group {io_clk} \
    -group {aon_clk}
