// Interrupt priority controller — aggregates interrupt sources from
// multiple subsystems, generates prioritized IRQ to CPU

module interrupt_controller (
    input  wire        sys_clk,
    input  wire        rst_n,

    // Interrupt sources (from various subsystems)
    input  wire        uart_irq,        // from uart_subsystem (per_clk domain, synced)
    input  wire        dma_done_irq,    // from dma_engine (dma_clk domain, synced)
    input  wire        wdog_bark,       // from watchdog (aon_clk domain, synced)
    input  wire [2:0]  pwr_status,      // from power_manager (aon_clk domain, synced)

    // SPI interrupt (spi_clk domain, synced separately)
    input  wire        spi_done,

    // CPU interface
    output reg  [7:0]  irq_pending,
    output wire        irq_any,

    // Wakeup logic
    output reg         wakeup_trigger
);

    // Priority encoding — combine all interrupt sources
    always @(posedge sys_clk or negedge rst_n) begin
        if (!rst_n) begin
            irq_pending <= 8'd0;
        end else begin
            irq_pending[0] <= uart_irq;
            irq_pending[1] <= dma_done_irq;
            irq_pending[2] <= wdog_bark;
            irq_pending[3] <= spi_done;
            irq_pending[4] <= pwr_status[0];  // sleep_req from power_manager
            irq_pending[5] <= pwr_status[1];  // wakeup from power_manager
            irq_pending[6] <= 1'b0;
            irq_pending[7] <= 1'b0;
        end
    end

    assign irq_any = |irq_pending;

    // Wakeup logic: combine wdog_bark AND pwr_status[1] (wakeup)
    // NOTE: wdog_bark and pwr_status[1] were independently synchronized
    //       from the aon_clk domain in their respective modules.
    //       Combining them here creates a reconvergence point.
    always @(posedge sys_clk or negedge rst_n) begin
        if (!rst_n)
            wakeup_trigger <= 1'b0;
        else
            wakeup_trigger <= wdog_bark & pwr_status[1];
    end

endmodule
