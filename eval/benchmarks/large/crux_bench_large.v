// Multi-subsystem SoC
// Domains: sys_clk, per_clk, dma_clk, usb_clk, aon_clk, spi_clk

module crux_bench_large (
    input  wire        sys_clk,
    input  wire        per_clk,
    input  wire        dma_clk,
    input  wire        usb_clk,
    input  wire        aon_clk,
    input  wire        spi_clk,
    input  wire        rst_n,

    // UART
    input  wire [7:0]  uart_wdata,
    input  wire        uart_write,
    input  wire        uart_read,
    output wire [7:0]  uart_rdata,
    input  wire        uart_rx,
    output wire        uart_tx,

    // DMA
    input  wire [31:0] dma_desc,
    input  wire        dma_desc_write,
    input  wire [1:0]  dma_channel,
    output wire [31:0] dma_mem_wdata,
    output wire        dma_mem_write,

    // USB
    input  wire [7:0]  usb_rx_data,
    input  wire        usb_rx_valid,
    output wire [7:0]  usb_tx_data,

    // SPI
    input  wire [7:0]  spi_rx_data,
    input  wire        spi_rx_valid,
    output wire [7:0]  spi_tx_data,
    output wire        spi_tx_valid,

    // Watchdog
    input  wire [15:0] wdog_timeout,
    input  wire        wdog_timeout_write,
    input  wire        wdog_kick,

    // Power
    input  wire        sleep_req,
    input  wire        wakeup_src,
    input  wire        low_power_hint,

    // CPU interface
    output wire [7:0]  irq_pending,
    output wire        irq_any,
    output wire        wakeup_trigger,
    output wire [2:0]  pwr_status,
    output wire        sleep_ack,

    // System outputs
    output wire [7:0]  sys_rx_data,
    output wire        sys_rx_valid,

    // Debug / status
    output reg  [7:0]  sys_debug,
    output reg         per_flag_out,
    output reg         dma_err_out
);

    // Internal signals
    wire uart_irq, dma_done_irq, wdog_bark, wdog_bite;
    wire spi_done;

    // UART subsystem (sys_clk + per_clk)
    uart_subsystem u_uart (
        .sys_clk(sys_clk), .per_clk(per_clk), .rst_n(rst_n),
        .bus_wdata(uart_wdata), .bus_write(uart_write),
        .bus_read(uart_read), .bus_rdata(uart_rdata),
        .rx_i(uart_rx), .tx_o(uart_tx), .irq_o(uart_irq)
    );

    // DMA engine (sys_clk + dma_clk + usb_clk)
    dma_engine u_dma (
        .sys_clk(sys_clk), .dma_clk(dma_clk), .usb_clk(usb_clk), .rst_n(rst_n),
        .desc_wdata(dma_desc), .desc_write(dma_desc_write),
        .channel_sel(dma_channel), .dma_done_irq(dma_done_irq),
        .mem_wdata(dma_mem_wdata), .mem_write(dma_mem_write),
        .usb_data_in(usb_rx_data), .usb_data_valid(usb_rx_valid),
        .usb_data_out(usb_tx_data)
    );

    // Watchdog (sys_clk + aon_clk)
    watchdog u_wdog (
        .sys_clk(sys_clk), .aon_clk(aon_clk), .rst_n(rst_n),
        .timeout_val(wdog_timeout), .timeout_write(wdog_timeout_write),
        .kick(wdog_kick), .bark_irq(wdog_bark), .bite_rst(wdog_bite)
    );

    // Power manager (sys_clk + aon_clk)
    power_manager u_pwr (
        .sys_clk(sys_clk), .aon_clk(aon_clk), .rst_n(rst_n),
        .sleep_req(sleep_req), .wakeup_src(wakeup_src),
        .low_power_hint(low_power_hint),
        .pwr_status(pwr_status), .sleep_ack(sleep_ack)
    );

    // SPI bridge (sys_clk + spi_clk)
    spi_bridge u_spi (
        .sys_clk(sys_clk), .spi_clk(spi_clk), .rst_n(rst_n),
        .spi_rx_data(spi_rx_data), .spi_rx_valid(spi_rx_valid),
        .spi_tx_data(spi_tx_data), .spi_tx_valid(spi_tx_valid),
        .sys_rx_data(sys_rx_data), .sys_rx_valid(sys_rx_valid),
        .sys_tx_data(uart_wdata), .sys_tx_write(uart_write),
        .spi_done(spi_done)
    );

    // Interrupt controller (sys_clk, aggregates all irq sources)
    interrupt_controller u_irq (
        .sys_clk(sys_clk), .rst_n(rst_n),
        .uart_irq(uart_irq), .dma_done_irq(dma_done_irq),
        .wdog_bark(wdog_bark), .pwr_status(pwr_status),
        .spi_done(spi_done),
        .irq_pending(irq_pending), .irq_any(irq_any),
        .wakeup_trigger(wakeup_trigger)
    );

    // DMA status forwarding
    reg dma_busy;
    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) dma_busy <= 0;
        else        dma_busy <= dma_mem_write;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) sys_debug <= 0;
        else        sys_debug <= {7'b0, dma_busy};

    // per_clk activity with combo before sync
    reg per_activity;
    always @(posedge per_clk or negedge rst_n)
        if (!rst_n) per_activity <= 0;
        else        per_activity <= uart_rx;

    wire per_masked = per_activity & uart_irq;
    reg per_sync1, per_sync2;
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin per_sync1 <= 0; per_sync2 <= 0; end
        else        begin per_sync1 <= per_masked; per_sync2 <= per_sync1; end
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) per_flag_out <= 0;
        else        per_flag_out <= per_sync2;

    // aon_clk reset drives dma_clk register
    reg aon_err;
    always @(posedge aon_clk or negedge rst_n)
        if (!rst_n) aon_err <= 1;
        else        aon_err <= ~wdog_kick;

    always @(posedge dma_clk or negedge aon_err)
        if (!aon_err) dma_err_out <= 0;
        else          dma_err_out <= dma_mem_write;

endmodule
