// Two independently synced signals reconverge via AND gate (unsafe)

module reconvergence_unsafe (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire sig_a_in,
    input  wire sig_b_in,
    output reg  combined_out
);

    // Source domain: clk_a
    reg sig_a, sig_b;
    always @(posedge clk_a or negedge rst_n) begin
        if (!rst_n) begin
            sig_a <= 1'b0;
            sig_b <= 1'b0;
        end else begin
            sig_a <= sig_a_in;
            sig_b <= sig_b_in;
        end
    end

    // Independent 2FF sync for sig_a
    reg sync_a1, sync_a2;
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n) begin
            sync_a1 <= 1'b0;
            sync_a2 <= 1'b0;
        end else begin
            sync_a1 <= sig_a;
            sync_a2 <= sync_a1;
        end
    end

    // Independent 2FF sync for sig_b
    reg sync_b1, sync_b2;
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n) begin
            sync_b1 <= 1'b0;
            sync_b2 <= 1'b0;
        end else begin
            sync_b1 <= sig_b;
            sync_b2 <= sync_b1;
        end
    end

    // RECONVERGENCE: sync_a2 and sync_b2 are ANDed together
    // If sig_a and sig_b change simultaneously in clk_a, the clk_b receiver
    // might see them arrive at different cycles → inconsistent state
    wire combined = sync_a2 & sync_b2;

    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            combined_out <= 1'b0;
        else
            combined_out <= combined;
    end

endmodule
