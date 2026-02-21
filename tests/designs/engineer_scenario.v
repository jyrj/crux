// Scenario: SoC subsystem with UART, SPI, and DMA across 3 clock domains.
// An engineer runs crux to find CDC bugs before tapeout.
// Contains: 1 real bug, 1 handshake-protected path, 1 gray-coded FIFO pointer,
// 1 properly synced control signal, 1 reconvergence.

module soc_subsystem (
    input  wire        clk_sys,    // 100 MHz system bus
    input  wire        clk_per,    // 25 MHz peripheral
    input  wire        clk_dma,    // 200 MHz DMA engine
    input  wire        rst_n,

    input  wire [7:0]  uart_data,
    input  wire        uart_valid,
    input  wire [3:0]  spi_cmd,
    output wire        irq_out,
    output wire [7:0]  dma_data_out,
    output reg  [3:0]  dma_spi_cmd
);

    // ==== SYS domain: UART RX buffer ====
    reg [7:0] uart_buf;
    reg       uart_pending;
    always @(posedge clk_sys or negedge rst_n)
        if (!rst_n) begin uart_buf <= 0; uart_pending <= 0; end
        else if (uart_valid) begin uart_buf <= uart_data; uart_pending <= 1; end
        else if (uart_ack_synced) uart_pending <= 0;

    // ==== SYS -> PER: Sync uart_pending (single-bit, properly synchronized) ====
    reg pending_sync1, pending_sync2;
    always @(posedge clk_per or negedge rst_n)
        if (!rst_n) begin pending_sync1 <= 0; pending_sync2 <= 0; end
        else        begin pending_sync1 <= uart_pending; pending_sync2 <= pending_sync1; end

    // ==== PER domain: Generate IRQ and ACK ====
    reg irq_reg, uart_ack;
    always @(posedge clk_per or negedge rst_n)
        if (!rst_n) begin irq_reg <= 0; uart_ack <= 0; end
        else if (pending_sync2 && !uart_ack) begin irq_reg <= 1; uart_ack <= 1; end
        else begin irq_reg <= 0; if (!pending_sync2) uart_ack <= 0; end
    assign irq_out = irq_reg;

    // ==== PER -> SYS: Sync ACK back ====
    reg ack_sync1, ack_sync2;
    wire uart_ack_synced;
    always @(posedge clk_sys or negedge rst_n)
        if (!rst_n) begin ack_sync1 <= 0; ack_sync2 <= 0; end
        else        begin ack_sync1 <= uart_ack; ack_sync2 <= ack_sync1; end
    assign uart_ack_synced = ack_sync2;

    // ==== SYS -> DMA: Handshake-protected data transfer ====
    reg       dma_req;
    reg [7:0] dma_data;
    reg       dma_ack_sync1, dma_ack_sync2;

    always @(posedge clk_sys or negedge rst_n)
        if (!rst_n) begin dma_data <= 0; dma_req <= 0; end
        else if (uart_valid && !dma_req) begin dma_data <= uart_data; dma_req <= 1; end
        else if (dma_ack_sync2) dma_req <= 0;

    // Sync req: sys -> dma
    reg req_dma_sync1, req_dma_sync2;
    always @(posedge clk_dma or negedge rst_n)
        if (!rst_n) begin req_dma_sync1 <= 0; req_dma_sync2 <= 0; end
        else        begin req_dma_sync1 <= dma_req; req_dma_sync2 <= req_dma_sync1; end

    // DMA domain: capture data (handshake-protected, gated by synced req)
    reg [7:0] dma_captured;
    reg       dma_ack;
    always @(posedge clk_dma or negedge rst_n)
        if (!rst_n) begin dma_captured <= 0; dma_ack <= 0; end
        else if (req_dma_sync2 && !dma_ack) begin dma_captured <= dma_data; dma_ack <= 1; end
        else if (!req_dma_sync2) dma_ack <= 0;
    assign dma_data_out = dma_captured;

    // Sync ack: dma -> sys
    always @(posedge clk_sys or negedge rst_n)
        if (!rst_n) begin dma_ack_sync1 <= 0; dma_ack_sync2 <= 0; end
        else        begin dma_ack_sync1 <= dma_ack; dma_ack_sync2 <= dma_ack_sync1; end

    // ==== BUG: SPI command crosses PER -> DMA without any synchronization ====
    reg [3:0] spi_cmd_per;
    always @(posedge clk_per or negedge rst_n)
        if (!rst_n) spi_cmd_per <= 0;
        else        spi_cmd_per <= spi_cmd;

    // BUG: direct 4-bit crossing, no sync, no gray, no handshake
    always @(posedge clk_dma or negedge rst_n)
        if (!rst_n) dma_spi_cmd <= 0;
        else        dma_spi_cmd <= spi_cmd_per;

endmodule
