create_clock -name sys_clk -period 10.0  [get_ports sys_clk]
create_clock -name per_clk -period 40.0  [get_ports per_clk]
create_clock -name aon_clk -period 5000  [get_ports aon_clk]
create_clock -name usb_clk -period 20.83 [get_ports usb_clk]

set_clock_groups -asynchronous \
    -group {sys_clk} \
    -group {per_clk} \
    -group {aon_clk} \
    -group {usb_clk}
