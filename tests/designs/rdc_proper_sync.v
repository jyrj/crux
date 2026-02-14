// Reset sync: async assert, sync de-assert via 2FF chain (prim_rst_sync pattern)

module rdc_proper_sync (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire data_in,
    input  wire reset_trigger,
    output reg  data_out
);

    // Generate a reset in clk_a domain
    reg rst_a;
    always @(posedge clk_a or negedge rst_n) begin
        if (!rst_n)
            rst_a <= 1'b0;
        else
            rst_a <= reset_trigger;
    end

    // Reset synchronizer: async assert, sync de-assert
    // When rst_a goes low (assert), both sync stages immediately reset to 0.
    // When rst_a goes high (de-assert), it takes 2 clk_b cycles to propagate.
    reg rst_sync1, rst_sync2;
    always @(posedge clk_b or negedge rst_a) begin
        if (!rst_a) begin
            rst_sync1 <= 1'b0;
            rst_sync2 <= 1'b0;
        end else begin
            rst_sync1 <= 1'b1;    // D input tied to 1 (release value)
            rst_sync2 <= rst_sync1;
        end
    end

    // Source data in clk_b domain
    reg data_b;
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            data_b <= 1'b0;
        else
            data_b <= data_in;
    end

    // Safe: rst_sync2 is properly synchronized to clk_b
    always @(posedge clk_b or negedge rst_sync2) begin
        if (!rst_sync2)
            data_out <= 1'b0;
        else
            data_out <= data_b;
    end

endmodule
