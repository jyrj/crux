// Missing synchronizer: clk_a -> clk_b with no sync

module simple_cdc (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire data_in,
    output reg  data_out
);

    reg data_a;

    // Source domain: clk_a
    always @(posedge clk_a or negedge rst_n) begin
        if (!rst_n)
            data_a <= 1'b0;
        else
            data_a <= data_in;
    end

    // Destination domain: clk_b - VIOLATION: no synchronizer!
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            data_out <= 1'b0;
        else
            data_out <= data_a;  // Direct CDC crossing - metastability risk
    end

endmodule
