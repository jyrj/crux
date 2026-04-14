// crux_bench_small: Multi-peripheral microcontroller subsystem
// Multi-peripheral microcontroller subsystem, 4 clock domains
// Domains:
//   sys_clk  (100 MHz) - CPU, bus, control logic
//   per_clk  (25 MHz)  - UART, GPIO
//   aon_clk  (200 kHz) - watchdog, wakeup
//   usb_clk  (48 MHz)  - USB PHY interface

// --- 2FF synchronizer primitive ---
module sync_2ff #(parameter W = 1) (
    input  wire         clk_i,
    input  wire         rst_ni,
    input  wire [W-1:0] d_i,
    output reg  [W-1:0] q_o
);
    reg [W-1:0] meta;
    always @(posedge clk_i or negedge rst_ni)
        if (!rst_ni) begin meta <= '0; q_o <= '0; end
        else         begin meta <= d_i; q_o <= meta; end
endmodule

// --- Pulse synchronizer ---
module pulse_sync (
    input  wire clk_src_i, rst_src_ni, src_pulse_i,
    input  wire clk_dst_i, rst_dst_ni,
    output wire dst_pulse_o
);
    reg src_level;
    always @(posedge clk_src_i or negedge rst_src_ni)
        if (!rst_src_ni) src_level <= 0;
        else             src_level <= src_level ^ src_pulse_i;

    wire dst_level;
    sync_2ff #(.W(1)) u_sync (
        .clk_i(clk_dst_i), .rst_ni(rst_dst_ni),
        .d_i(src_level), .q_o(dst_level)
    );

    reg dst_level_q;
    always @(posedge clk_dst_i or negedge rst_dst_ni)
        if (!rst_dst_ni) dst_level_q <= 0;
        else             dst_level_q <= dst_level;

    assign dst_pulse_o = dst_level ^ dst_level_q;
endmodule

// --- Gray-coded 4-bit pointer crossing ---
module gray_ptr_sync (
    input  wire       clk_src_i, rst_src_ni,
    input  wire [3:0] bin_ptr_i,
    input  wire       clk_dst_i, rst_dst_ni,
    output reg  [3:0] gray_ptr_o
);
    reg [3:0] gray_q;
    always @(posedge clk_src_i or negedge rst_src_ni)
        if (!rst_src_ni) gray_q <= 0;
        else             gray_q <= bin_ptr_i ^ (bin_ptr_i >> 1);

    reg [3:0] sync1, sync2;
    always @(posedge clk_dst_i or negedge rst_dst_ni)
        if (!rst_dst_ni) begin sync1 <= 0; sync2 <= 0; end
        else             begin sync1 <= gray_q; sync2 <= sync1; end

    always @(posedge clk_dst_i or negedge rst_dst_ni)
        if (!rst_dst_ni) gray_ptr_o <= 0;
        else             gray_ptr_o <= sync2;
endmodule

// Top-level SoC
module crux_bench_small (
    input  wire        sys_clk,
    input  wire        per_clk,
    input  wire        aon_clk,
    input  wire        usb_clk,
    input  wire        rst_n,

    // UART interface (per_clk domain)
    input  wire [7:0]  uart_rx_data,
    input  wire        uart_rx_valid,
    output wire        uart_tx_ready,

    // GPIO (per_clk domain)
    input  wire [7:0]  gpio_in,
    output reg  [7:0]  gpio_out,

    // USB (usb_clk domain)
    input  wire [7:0]  usb_rx_data,
    input  wire        usb_rx_valid,
    output reg  [7:0]  usb_tx_data,

    // Watchdog (aon_clk domain)
    input  wire        wdog_kick,
    output wire        wdog_bark,

    // Wakeup (aon_clk -> sys_clk)
    input  wire        wakeup_event,
    output wire        wakeup_ack,

    // DMA (sys_clk -> usb_clk, handshake)
    output reg  [7:0]  dma_data_out,
    output wire [3:0]  fifo_wptr_synced,

    // Additional status outputs
    output reg         per_usb_flag,
    output reg         usb_mask_synced,
    output reg         aon_error_latch
);

    //
    // sys_clk domain: CPU-side registers
    //
    reg [7:0]  cpu_tx_data;
    reg        cpu_tx_valid;
    reg [7:0]  cpu_status;
    reg [3:0]  fifo_wptr;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin
            cpu_tx_data  <= 0;
            cpu_tx_valid <= 0;
            cpu_status   <= 0;
            fifo_wptr    <= 0;
        end else begin
            cpu_tx_data  <= uart_rx_data;  // loopback for test
            cpu_tx_valid <= uart_rx_valid;
            cpu_status   <= gpio_in;
            fifo_wptr    <= fifo_wptr + (uart_rx_valid ? 4'd1 : 4'd0);
        end

    //
    //
    //
    pulse_sync u_uart_tx_pulse (
        .clk_src_i(sys_clk), .rst_src_ni(rst_n), .src_pulse_i(cpu_tx_valid),
        .clk_dst_i(per_clk), .rst_dst_ni(rst_n), .dst_pulse_o(uart_tx_ready)
    );

    //
    //
    //
    gray_ptr_sync u_fifo_ptr (
        .clk_src_i(sys_clk), .rst_src_ni(rst_n), .bin_ptr_i(fifo_wptr),
        .clk_dst_i(usb_clk), .rst_dst_ni(rst_n), .gray_ptr_o(fifo_wptr_synced)
    );

    //
    //
    //
    wire wakeup_synced;
    sync_2ff #(.W(1)) u_wakeup_sync (
        .clk_i(sys_clk), .rst_ni(rst_n),
        .d_i(wakeup_event), .q_o(wakeup_synced)
    );
    reg wakeup_ack_r;
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) wakeup_ack_r <= 0;
        else        wakeup_ack_r <= wakeup_synced;
    assign wakeup_ack = wakeup_ack_r;

    //
    //
    //
    wire cpu_valid_per;
    sync_2ff #(.W(1)) u_ctrl_sync (
        .clk_i(per_clk), .rst_ni(rst_n),
        .d_i(cpu_tx_valid), .q_o(cpu_valid_per)
    );

    //
    //
    //
    reg [7:0] gpio_captured;
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) gpio_captured <= 0;
        else        gpio_captured <= gpio_in;

    wire gpio_flag;
    reg  gpio_flag_per;
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) gpio_flag_per <= 0;
        else        gpio_flag_per <= |gpio_in;

    sync_2ff #(.W(1)) u_gpio_sync (
        .clk_i(sys_clk), .rst_ni(rst_n),
        .d_i(gpio_flag_per), .q_o(gpio_flag)
    );

    //
    //
    //
    reg       dma_req;
    reg [7:0] dma_data;
    reg       dma_ack_sync1, dma_ack_sync2;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin dma_data <= 0; dma_req <= 0; end
        else if (cpu_tx_valid && !dma_req) begin dma_data <= cpu_tx_data; dma_req <= 1; end
        else if (dma_ack_sync2) dma_req <= 0;

    reg req_usb_sync1, req_usb_sync2;
    always @(posedge usb_clk or negedge rst_n)
        if (!rst_n) begin req_usb_sync1 <= 0; req_usb_sync2 <= 0; end
        else        begin req_usb_sync1 <= dma_req; req_usb_sync2 <= req_usb_sync1; end

    reg dma_ack;
    always @(posedge usb_clk or negedge rst_n)
        if (!rst_n) begin dma_data_out <= 0; dma_ack <= 0; end
        else if (req_usb_sync2 && !dma_ack) begin dma_data_out <= dma_data; dma_ack <= 1; end
        else if (!req_usb_sync2) dma_ack <= 0;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin dma_ack_sync1 <= 0; dma_ack_sync2 <= 0; end
        else        begin dma_ack_sync1 <= dma_ack; dma_ack_sync2 <= dma_ack_sync1; end

    //
    //
    //
    wire wdog_kick_synced;
    sync_2ff #(.W(1)) u_wdog_sync (
        .clk_i(aon_clk), .rst_ni(rst_n),
        .d_i(wdog_kick), .q_o(wdog_kick_synced)
    );

    reg [15:0] wdog_cnt;
    always @(posedge aon_clk or negedge rst_n)
        if (!rst_n)            wdog_cnt <= 0;
        else if (wdog_kick_synced) wdog_cnt <= 0;
        else                   wdog_cnt <= wdog_cnt + 1;
    assign wdog_bark = (wdog_cnt == 16'hFFFF);

    //
    //
    //
    reg usb_valid_r;
    always @(posedge usb_clk or negedge rst_n)
        if (!rst_n) usb_valid_r <= 0;
        else        usb_valid_r <= usb_rx_valid;

    wire usb_valid_synced;
    sync_2ff #(.W(1)) u_usb_valid_sync (
        .clk_i(sys_clk), .rst_ni(rst_n),
        .d_i(usb_valid_r), .q_o(usb_valid_synced)
    );

    //
    //
    //
    reg per_usb_flag;
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) per_usb_flag <= 0;
        else        per_usb_flag <= usb_valid_r;  

    //
    //
    //
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) gpio_out <= 0;
        else        gpio_out <= cpu_status;  

    //
    //
    // usb_tx_data is registered in usb_clk, masked by usb_valid_r (also usb_clk),
    // then fed to a sync stage in sys_clk with combo logic in between
    //
    wire usb_flag_masked = usb_tx_data[0] & usb_valid_r;  
    reg usb_mask_sync1;
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin usb_mask_sync1 <= 0; usb_mask_synced <= 0; end
        else        begin usb_mask_sync1 <= usb_flag_masked; usb_mask_synced <= usb_mask_sync1; end

    //
    //
    //
    reg per_rst_gen;
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) per_rst_gen <= 1;
        else        per_rst_gen <= ~gpio_in[7];  // generates a reset from per_clk

    reg aon_error_latch;
    always @(posedge aon_clk or negedge per_rst_gen)
        if (!per_rst_gen) aon_error_latch <= 0;
        else              aon_error_latch <= wdog_kick_synced;

    // USB TX output
    always @(posedge usb_clk or negedge rst_n)
        if (!rst_n) usb_tx_data <= 0;
        else        usb_tx_data <= usb_rx_data;

endmodule
