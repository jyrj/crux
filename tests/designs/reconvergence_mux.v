// Two independently synced signals reconverge via MUX (usually safe)

module reconvergence_mux (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire sig_a_in,
    input  wire sig_b_in,
    input  wire sel_in,
    output reg  mux_out
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

    // Select signal in clk_b domain
    reg sel_b;
    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            sel_b <= 1'b0;
        else
            sel_b <= sel_in;
    end

    // Reconvergence through MUX - only one path is active at a time
    wire muxed = sel_b ? sync_a2 : sync_b2;

    always @(posedge clk_b or negedge rst_n) begin
        if (!rst_n)
            mux_out <= 1'b0;
        else
            mux_out <= muxed;
    end

endmodule
