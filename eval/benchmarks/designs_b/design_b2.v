// Clock manager shadow register error detection
// Based on lowRISC/opentitan hw/top_earlgrey/ip_autogen/clkmgr/rtl/clkmgr_reg_top.sv
// Based on lowRISC/opentitan clkmgr_reg_top

module clkmgr_shadow_reg (
    input  wire        clk_main,
    input  wire        clk_io_div4,
    input  wire        rst_n,

    input  wire [7:0]  reg_wdata,
    input  wire        reg_write,
    output wire        err_alert_o
);

    reg [7:0] reg_q, shadow_q;

    always @(posedge clk_main or negedge rst_n)
        if (!rst_n) begin reg_q <= 0; shadow_q <= 0; end
        else if (reg_write) begin reg_q <= reg_wdata; shadow_q <= reg_wdata; end

    wire err_storage = (reg_q != shadow_q);

    reg err_sync1, err_sync2;
    always @(posedge clk_io_div4 or negedge rst_n)
        if (!rst_n) begin err_sync1 <= 0; err_sync2 <= 0; end
        else        begin err_sync1 <= err_storage; err_sync2 <= err_sync1; end

    assign err_alert_o = err_sync2;

endmodule
