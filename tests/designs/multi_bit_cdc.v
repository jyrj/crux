// 4-bit bus crossing clk_a -> clk_b without gray code or handshake

module multi_bit_cdc (
    input  wire       clk_a,
    input  wire       clk_b,
    input  wire       rst_n,
    input  wire [3:0] data_in,
    output reg  [3:0] data_out
);

    reg [3:0] data_a;

    // Source domain: clk_a
    always @(posedge clk_a or negedge rst_n) begin
        if (!rst_n)
            data_a <= 4'b0;
        else
            data_a <= data_in;
    end

    // Destination domain: clk_b - VIOLATION: multi-bit CDC with no encoding
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            data_out <= 4'b0;
        else
            data_out <= data_a;  // All 4 bits cross unsynchronized
    end

endmodule
