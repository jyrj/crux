// combo_before_sync.v - Combinational logic before synchronizer (MUST flag)
// A signal from clk_a passes through combinational logic before
// reaching a synchronizer in clk_b domain. The combo logic can
// produce glitches that the synchronizer may capture incorrectly.

module combo_before_sync (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire data_in,
    input  wire mask,
    output wire data_out
);

    reg data_a;
    reg sync_1, sync_2;
    wire data_masked;

    // Source domain: clk_a
    always @(posedge clk_a or negedge rst_n) begin
        if (!rst_n)
            data_a <= 1'b0;
        else
            data_a <= data_in;
    end

    // VIOLATION: combinational logic on CDC path before synchronizer
    assign data_masked = data_a & mask;

    // Destination domain: clk_b
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n) begin
            sync_1 <= 1'b0;
            sync_2 <= 1'b0;
        end else begin
            sync_1 <= data_masked;  // Combo logic feeds sync stage 1
            sync_2 <= sync_1;
        end
    end

    assign data_out = sync_2;

endmodule
