// Hardened counter primitive with cross-counter integrity check
// Based on lowRISC/opentitan hw/ip/prim/rtl/prim_count.sv
// Based on lowRISC/opentitan prim_count

module prim_count_hardened #(
    parameter WIDTH = 4
) (
    input  wire             clk_i,
    input  wire             rst_ni,
    input  wire             clr_i,
    input  wire             incr_en_i,
    output wire [WIDTH-1:0] cnt_o,
    output wire             err_o
);

    reg [WIDTH-1:0] cnt_q;
    always @(posedge clk_i or negedge rst_ni)
        if (!rst_ni)    cnt_q <= 0;
        else if (clr_i) cnt_q <= 0;
        else if (incr_en_i) cnt_q <= cnt_q + 1;

    reg [WIDTH-1:0] cnt_sec_q;
    always @(posedge clk_i or negedge rst_ni)
        if (!rst_ni)    cnt_sec_q <= {WIDTH{1'b1}};
        else if (clr_i) cnt_sec_q <= {WIDTH{1'b1}};
        else if (incr_en_i) cnt_sec_q <= cnt_sec_q - 1;

    assign cnt_o = cnt_q;

    wire [WIDTH:0] sum = {1'b0, cnt_q} + {1'b0, cnt_sec_q};
    assign err_o = (sum != {1'b0, {WIDTH{1'b1}}});

endmodule

module count_cdc_wrapper (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire incr,
    output reg  error_flag
);
    wire [3:0] cnt;
    wire       cnt_err;

    prim_count_hardened #(.WIDTH(4)) u_count (
        .clk_i(clk_a), .rst_ni(rst_n),
        .clr_i(1'b0), .incr_en_i(incr),
        .cnt_o(cnt), .err_o(cnt_err)
    );

    reg err_sync1, err_sync2;
    always @(posedge clk_b or negedge rst_n)
        if (!rst_n) begin err_sync1 <= 0; err_sync2 <= 0; end
        else        begin err_sync1 <= cnt_err; err_sync2 <= err_sync1; end

    always @(posedge clk_b or negedge rst_n)
        if (!rst_n) error_flag <= 0;
        else        error_flag <= err_sync2;
endmodule
