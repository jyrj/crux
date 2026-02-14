// Proper 2FF synchronizer: clk_a -> clk_b, should pass clean

module simple_sync (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire data_in,
    output wire data_out
);

    reg data_a;
    reg sync_1, sync_2;

    // Source domain: clk_a
    always @(posedge clk_a or negedge rst_n) begin
        if (!rst_n)
            data_a <= 1'b0;
        else
            data_a <= data_in;
    end

    // Destination domain: clk_b - proper 2FF synchronizer
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n) begin
            sync_1 <= 1'b0;
            sync_2 <= 1'b0;
        end else begin
            sync_1 <= data_a;   // Sync stage 1: captures metastable value
            sync_2 <= sync_1;   // Sync stage 2: resolves metastability
        end
    end

    assign data_out = sync_2;

endmodule
