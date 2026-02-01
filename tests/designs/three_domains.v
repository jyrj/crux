// three_domains.v - Three clock domains with mixed sync/unsync crossings
// Tests: multiple domains, some crossings synchronized, some not.
// Mimics a real SoC scenario: sys_clk, io_clk, slow_clk

module three_domains (
    input  wire sys_clk,
    input  wire io_clk,
    input  wire slow_clk,
    input  wire rst_n,
    input  wire data_in,
    output wire data_io_out,
    output reg  data_slow_out
);

    reg data_sys;
    reg io_sync1, io_sync2;

    // System domain
    always @(posedge sys_clk or negedge rst_n) begin
        if (!rst_n)
            data_sys <= 1'b0;
        else
            data_sys <= data_in;
    end

    // IO domain: PROPERLY synchronized from sys_clk
    always @(posedge io_clk or negedge rst_n) begin
        if (!rst_n) begin
            io_sync1 <= 1'b0;
            io_sync2 <= 1'b0;
        end else begin
            io_sync1 <= data_sys;
            io_sync2 <= io_sync1;
        end
    end
    assign data_io_out = io_sync2;

    // Slow domain: MISSING synchronizer from sys_clk
    always @(posedge slow_clk or negedge rst_n) begin
        if (!rst_n)
            data_slow_out <= 1'b0;
        else
            data_slow_out <= data_sys;  // CDC violation!
    end

endmodule
