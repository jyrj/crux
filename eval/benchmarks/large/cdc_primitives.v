// CDC primitive library (based on OpenTitan prim_flop_2sync / prim_pulse_sync)
// Used by the SoC benchmark modules

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

module gray_sync #(parameter W = 4) (
    input  wire         clk_src_i, rst_src_ni,
    input  wire [W-1:0] bin_i,
    input  wire         clk_dst_i, rst_dst_ni,
    output reg  [W-1:0] gray_o
);
    reg [W-1:0] gray_q;
    always @(posedge clk_src_i or negedge rst_src_ni)
        if (!rst_src_ni) gray_q <= 0;
        else             gray_q <= bin_i ^ (bin_i >> 1);

    reg [W-1:0] sync1, sync2;
    always @(posedge clk_dst_i or negedge rst_dst_ni)
        if (!rst_dst_ni) begin sync1 <= 0; sync2 <= 0; end
        else             begin sync1 <= gray_q; sync2 <= sync1; end

    always @(posedge clk_dst_i or negedge rst_dst_ni)
        if (!rst_dst_ni) gray_o <= 0;
        else             gray_o <= sync2;
endmodule

module reset_sync (
    input  wire clk_i,
    input  wire rst_ni,    // async raw reset
    output reg  rst_sync_o
);
    reg sync1;
    always @(posedge clk_i or negedge rst_ni)
        if (!rst_ni) begin sync1 <= 0; rst_sync_o <= 0; end
        else         begin sync1 <= 1; rst_sync_o <= sync1; end
endmodule
