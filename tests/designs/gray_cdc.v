// 4-bit binary counter with gray encoding crossing clk_a -> clk_b via 2FF sync
module gray_cdc (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    output reg [3:0] gray_out
);
    reg [3:0] bin_cnt;
    reg [3:0] gray_q;
    reg [3:0] sync1, sync2;

    // Binary counter in clk_a
    always @(posedge clk_a or negedge rst_n)
        if (!rst_n) bin_cnt <= 4'd0;
        else        bin_cnt <= bin_cnt + 4'd1;

    // Binary-to-gray conversion, registered in clk_a
    always @(posedge clk_a or negedge rst_n)
        if (!rst_n) gray_q <= 4'd0;
        else        gray_q <= bin_cnt ^ (bin_cnt >> 1);

    // 2FF sync in clk_b
    always @(posedge clk_b or negedge rst_n)
        if (!rst_n) begin sync1 <= 4'd0; sync2 <= 4'd0; end
        else        begin sync1 <= gray_q; sync2 <= sync1; end

    always @(posedge clk_b or negedge rst_n)
        if (!rst_n) gray_out <= 4'd0;
        else        gray_out <= sync2;
endmodule
