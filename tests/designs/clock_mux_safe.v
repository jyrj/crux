// Glitch-free clock mux: AND-OR with negedge select FFs
module clock_mux_safe (
    input  wire clk_a,
    input  wire clk_b,
    input  wire sel,
    input  wire rst_n,
    input  wire d,
    output reg  q
);
    // Select registers on negedge of respective clocks (prevents glitch during high phase)
    reg sel_a, sel_b;
    always @(negedge clk_a or negedge rst_n)
        if (!rst_n) sel_a <= 1'b1;   // default: clk_a selected
        else        sel_a <= sel & ~sel_b;

    always @(negedge clk_b or negedge rst_n)
        if (!rst_n) sel_b <= 1'b0;
        else        sel_b <= ~sel & ~sel_a;

    // AND-OR glitch-free mux
    wire clk_out = (clk_a & sel_a) | (clk_b & sel_b);

    always @(posedge clk_out or negedge rst_n)
        if (!rst_n) q <= 1'b0;
        else        q <= d;
endmodule
