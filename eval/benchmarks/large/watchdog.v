// Watchdog timer: aon_clk domain with sys_clk control interface
// Contains reset generation crossing back to sys_clk domain

module watchdog (
    input  wire        sys_clk,
    input  wire        aon_clk,
    input  wire        rst_n,

    // Control (sys_clk)
    input  wire [15:0] timeout_val,
    input  wire        timeout_write,
    input  wire        kick,
    output wire        bark_irq,
    output wire        bite_rst
);

    // ---- Sync kick: sys_clk -> aon_clk ----
    wire kick_synced;
    sync_2ff #(.W(1)) u_kick_sync (
        .clk_i(aon_clk), .rst_ni(rst_n), .d_i(kick), .q_o(kick_synced)
    );

    // ---- Sync timeout config: sys_clk -> aon_clk ----
    // Timeout configuration
    reg [15:0] timeout_aon;
    always @(posedge aon_clk or negedge rst_n)
        if (!rst_n) timeout_aon <= 16'hFFFF;
        else if (timeout_write) timeout_aon <= timeout_val;

    // ---- Watchdog counter (aon_clk domain) ----
    reg [15:0] wdog_cnt;
    reg        wdog_bark, wdog_bite;
    always @(posedge aon_clk or negedge rst_n)
        if (!rst_n) begin wdog_cnt <= 0; wdog_bark <= 0; wdog_bite <= 0; end
        else if (kick_synced) begin wdog_cnt <= 0; wdog_bark <= 0; wdog_bite <= 0; end
        else begin
            wdog_cnt <= wdog_cnt + 1;
            wdog_bark <= (wdog_cnt >= timeout_aon);
            wdog_bite <= (wdog_cnt >= {timeout_aon[14:0], 1'b0}); // 2x timeout
        end

    // ---- Sync bark IRQ: aon_clk -> sys_clk ----
    pulse_sync u_bark_pulse (
        .clk_src_i(aon_clk), .rst_src_ni(rst_n), .src_pulse_i(wdog_bark),
        .clk_dst_i(sys_clk), .rst_dst_ni(rst_n), .dst_pulse_o(bark_irq)
    );

    // Bite reset output
    assign bite_rst = wdog_bite;  // combinational path from aon_clk FF to output
    //
endmodule
