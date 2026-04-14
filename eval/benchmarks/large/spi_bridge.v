// SPI bridge — connects SPI peripheral clock domain to system bus
// Includes async FIFO for data transfer

module spi_bridge (
    input  wire        sys_clk,
    input  wire        spi_clk,
    input  wire        rst_n,

    // SPI interface (spi_clk domain)
    input  wire [7:0]  spi_rx_data,
    input  wire        spi_rx_valid,
    output reg  [7:0]  spi_tx_data,
    output reg         spi_tx_valid,

    // System interface (sys_clk domain)
    output reg  [7:0]  sys_rx_data,
    output reg         sys_rx_valid,
    input  wire [7:0]  sys_tx_data,
    input  wire        sys_tx_write,

    // Status
    output wire        spi_done
);

    // ---- RX FIFO: spi_clk -> sys_clk (gray-coded pointers) ----
    reg [7:0] rx_fifo [0:7];
    reg [3:0] rx_wptr;     // spi_clk domain
    reg [3:0] rx_rptr;     // sys_clk domain
    wire [3:0] rx_wptr_gray_sys;
    wire [3:0] rx_rptr_gray_spi;

    // Write side (spi_clk)
    always @(posedge spi_clk or negedge rst_n)
        if (!rst_n) rx_wptr <= 0;
        else if (spi_rx_valid) begin
            rx_fifo[rx_wptr[2:0]] <= spi_rx_data;
            rx_wptr <= rx_wptr + 1;
        end

    // Gray sync write pointer to sys_clk
    gray_sync #(.W(4)) u_rx_wptr_sync (
        .clk_src_i(spi_clk), .rst_src_ni(rst_n), .bin_i(rx_wptr),
        .clk_dst_i(sys_clk), .rst_dst_ni(rst_n), .gray_o(rx_wptr_gray_sys)
    );

    // Gray sync read pointer to spi_clk
    gray_sync #(.W(4)) u_rx_rptr_sync (
        .clk_src_i(sys_clk), .rst_src_ni(rst_n), .bin_i(rx_rptr),
        .clk_dst_i(spi_clk), .rst_dst_ni(rst_n), .gray_o(rx_rptr_gray_spi)
    );

    // Read side (sys_clk)
    wire rx_fifo_empty = (rx_wptr_gray_sys == rx_rptr[3:0]);
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin rx_rptr <= 0; sys_rx_data <= 0; sys_rx_valid <= 0; end
        else if (!rx_fifo_empty) begin
            sys_rx_data <= rx_fifo[rx_rptr[2:0]];
            sys_rx_valid <= 1;
            rx_rptr <= rx_rptr + 1;
        end else sys_rx_valid <= 0;

    // ---- TX FIFO: sys_clk -> spi_clk ----
    reg [7:0] tx_fifo [0:7];
    reg [3:0] tx_wptr;     // sys_clk domain
    reg [3:0] tx_rptr;     // spi_clk domain

    // Write side (sys_clk)
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) tx_wptr <= 0;
        else if (sys_tx_write) begin
            tx_fifo[tx_wptr[2:0]] <= sys_tx_data;
            tx_wptr <= tx_wptr + 1;
        end

    // TX read pointer sync
    
    
    wire [3:0] tx_rptr_synced;
    sync_2ff #(.W(4)) u_tx_rptr_sync (
        .clk_i(sys_clk), .rst_ni(rst_n),
        .d_i(tx_rptr), .q_o(tx_rptr_synced)
    );

    // Read side (spi_clk)
    // Gray sync write pointer to spi_clk (correct)
    wire [3:0] tx_wptr_gray_spi;
    gray_sync #(.W(4)) u_tx_wptr_sync (
        .clk_src_i(sys_clk), .rst_src_ni(rst_n), .bin_i(tx_wptr),
        .clk_dst_i(spi_clk), .rst_dst_ni(rst_n), .gray_o(tx_wptr_gray_spi)
    );

    wire tx_fifo_empty = (tx_wptr_gray_spi == tx_rptr[3:0]);
    always @(posedge spi_clk or negedge rst_n)
        if (!rst_n) begin tx_rptr <= 0; spi_tx_data <= 0; spi_tx_valid <= 0; end
        else if (!tx_fifo_empty) begin
            spi_tx_data <= tx_fifo[tx_rptr[2:0]];
            spi_tx_valid <= 1;
            tx_rptr <= tx_rptr + 1;
        end else spi_tx_valid <= 0;

    // Done signal — SPI transaction complete
    reg spi_done_r;
    always @(posedge spi_clk or negedge rst_n)
        if (!rst_n) spi_done_r <= 0;
        else        spi_done_r <= spi_tx_valid;

    // Sync done to sys_clk
    pulse_sync u_done_sync (
        .clk_src_i(spi_clk), .rst_src_ni(rst_n), .src_pulse_i(spi_done_r),
        .clk_dst_i(sys_clk), .rst_dst_ni(rst_n), .dst_pulse_o(spi_done)
    );

endmodule
