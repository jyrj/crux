// UART subsystem: per_clk domain peripheral with sys_clk bus interface
// Contains TX FIFO (gray-coded pointers), RX handshake, interrupt sync

module uart_subsystem (
    input  wire        sys_clk,
    input  wire        per_clk,
    input  wire        rst_n,

    // Bus interface (sys_clk domain)
    input  wire [7:0]  bus_wdata,
    input  wire        bus_write,
    input  wire        bus_read,
    output reg  [7:0]  bus_rdata,
    output wire        irq_o,

    // UART pins (per_clk domain)
    input  wire        rx_i,
    output reg         tx_o
);

    // ---- TX FIFO: sys_clk write side, per_clk read side ----
    reg [7:0] tx_fifo [0:15];
    reg [4:0] tx_wptr;        // sys_clk domain
    reg [4:0] tx_rptr;        // per_clk domain
    wire [4:0] tx_wptr_gray_per;  // gray-synced write pointer in per_clk
    wire [4:0] tx_rptr_gray_sys;  // gray-synced read pointer in sys_clk

    // Write side (sys_clk)
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) tx_wptr <= 0;
        else if (bus_write) begin
            tx_fifo[tx_wptr[3:0]] <= bus_wdata;
            tx_wptr <= tx_wptr + 1;
        end

    // Gray sync write pointer to per_clk
    gray_sync #(.W(5)) u_tx_wptr_sync (
        .clk_src_i(sys_clk), .rst_src_ni(rst_n), .bin_i(tx_wptr),
        .clk_dst_i(per_clk), .rst_dst_ni(rst_n), .gray_o(tx_wptr_gray_per)
    );

    // Gray sync read pointer to sys_clk
    gray_sync #(.W(5)) u_tx_rptr_sync (
        .clk_src_i(per_clk), .rst_src_ni(rst_n), .bin_i(tx_rptr),
        .clk_dst_i(sys_clk), .rst_dst_ni(rst_n), .gray_o(tx_rptr_gray_sys)
    );

    // Read side (per_clk)
    wire tx_fifo_empty = (tx_wptr_gray_per == tx_rptr[4:0]);  // approximate
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) begin tx_rptr <= 0; tx_o <= 1; end
        else if (!tx_fifo_empty) begin
            tx_o <= tx_fifo[tx_rptr[3:0]][0]; // simplified TX
            tx_rptr <= tx_rptr + 1;
        end

    // ---- RX path: per_clk -> sys_clk via handshake ----
    reg [7:0] rx_data_per;
    reg       rx_valid_per;
    reg       rx_ack_per;

    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) begin rx_data_per <= 0; rx_valid_per <= 0; end
        else if (rx_i && !rx_valid_per) begin
            rx_data_per <= {7'b0, rx_i}; // simplified
            rx_valid_per <= 1;
        end else if (rx_ack_per) rx_valid_per <= 0;

    // Sync rx_valid to sys_clk
    reg rx_valid_sync1, rx_valid_sync2;
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin rx_valid_sync1 <= 0; rx_valid_sync2 <= 0; end
        else        begin rx_valid_sync1 <= rx_valid_per; rx_valid_sync2 <= rx_valid_sync1; end

    // Capture RX data in sys_clk when valid arrives (handshake-protected)
    reg [7:0] rx_data_sys;
    reg       rx_ack_sys;
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin rx_data_sys <= 0; rx_ack_sys <= 0; end
        else if (rx_valid_sync2 && !rx_ack_sys) begin
            rx_data_sys <= rx_data_per;  // stable due to handshake
            rx_ack_sys <= 1;
        end else if (!rx_valid_sync2) rx_ack_sys <= 0;

    // Sync ack back to per_clk
    reg ack_sync1, ack_sync2;
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) begin ack_sync1 <= 0; ack_sync2 <= 0; end
        else        begin ack_sync1 <= rx_ack_sys; ack_sync2 <= ack_sync1; end
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) rx_ack_per <= 0;
        else        rx_ack_per <= ack_sync2;

    // Bus read
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) bus_rdata <= 0;
        else if (bus_read) bus_rdata <= rx_data_sys;

    // ---- Interrupt: per_clk -> sys_clk via pulse sync ----
    pulse_sync u_irq_pulse (
        .clk_src_i(per_clk), .rst_src_ni(rst_n), .src_pulse_i(rx_valid_per),
        .clk_dst_i(sys_clk), .rst_dst_ni(rst_n), .dst_pulse_o(irq_o)
    );
endmodule
