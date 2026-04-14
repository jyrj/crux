// Power manager: aon_clk domain with sys_clk status interface
// Contains reconvergence of independently synced status signals

module power_manager (
    input  wire        sys_clk,
    input  wire        aon_clk,
    input  wire        rst_n,

    // Status from aon_clk domain
    input  wire        sleep_req,
    input  wire        wakeup_src,
    input  wire        low_power_hint,

    // Output to sys_clk domain
    output reg  [2:0]  pwr_status,
    output reg         sleep_ack
);

    // ---- Sync each status signal independently: aon_clk -> sys_clk ----
    wire sleep_req_synced;
    sync_2ff #(.W(1)) u_sleep_sync (
        .clk_i(sys_clk), .rst_ni(rst_n), .d_i(sleep_req), .q_o(sleep_req_synced)
    );

    wire wakeup_synced;
    sync_2ff #(.W(1)) u_wakeup_sync (
        .clk_i(sys_clk), .rst_ni(rst_n), .d_i(wakeup_src), .q_o(wakeup_synced)
    );

    wire lp_hint_synced;
    sync_2ff #(.W(1)) u_lp_sync (
        .clk_i(sys_clk), .rst_ni(rst_n), .d_i(low_power_hint), .q_o(lp_hint_synced)
    );

    //
    // sleep_req_synced, wakeup_synced, lp_hint_synced arrive at different times
    // but are combined into pwr_status which is used for control decisions
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) pwr_status <= 0;
        else        pwr_status <= {lp_hint_synced, wakeup_synced, sleep_req_synced};

    // ---- Sleep ACK: sys_clk -> aon_clk ----
    reg sleep_ack_sys;
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) sleep_ack_sys <= 0;
        else        sleep_ack_sys <= sleep_req_synced;

    wire sleep_ack_aon;
    sync_2ff #(.W(1)) u_ack_sync (
        .clk_i(aon_clk), .rst_ni(rst_n), .d_i(sleep_ack_sys), .q_o(sleep_ack_aon)
    );

    always @(posedge aon_clk or negedge rst_n)
        if (!rst_n) sleep_ack <= 0;
        else        sleep_ack <= sleep_ack_aon;
endmodule
