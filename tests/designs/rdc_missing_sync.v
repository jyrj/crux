// Async reset from clk_a domain directly drives clk_b FFs (RDC bug)

module rdc_missing_sync (
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

    // Source data in clk_b domain
    reg data_b;
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            data_b <= 1'b0;
        else
            data_b <= data_in;
    end

    // BUG: rst_a (from clk_a domain) directly drives async reset of clk_b FF
    // Reset de-assertion is not synchronized to clk_b → metastability risk
    always @(posedge clk_b or negedge rst_a) begin
        if (!rst_a)
            data_out <= 1'b0;
        else
            data_out <= data_b;
    end

endmodule
