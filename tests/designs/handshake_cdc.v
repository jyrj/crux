// 8-bit data crossing clk_a -> clk_b with req/ack handshake
module handshake_cdc (
    input  wire       clk_a,
    input  wire       clk_b,
    input  wire       rst_n,
    input  wire [7:0] data_in,
    input  wire       send,
    output reg  [7:0] data_out,
    output reg        data_valid
);
    // Source domain (clk_a): latch data and assert req
    reg [7:0] data_hold;
    reg       req;
    reg       ack_sync1, ack_sync2;

    always @(posedge clk_a or negedge rst_n)
        if (!rst_n) begin
            data_hold <= 8'd0;
            req       <= 1'b0;
        end else if (send && !req) begin
            data_hold <= data_in;
            req       <= 1'b1;
        end else if (ack_sync2) begin
            req <= 1'b0;
        end

    // Sync req: clk_a -> clk_b
    reg req_sync1, req_sync2;
    always @(posedge clk_b or negedge rst_n)
        if (!rst_n) begin req_sync1 <= 0; req_sync2 <= 0; end
        else        begin req_sync1 <= req; req_sync2 <= req_sync1; end

    // Destination domain (clk_b): capture data when req arrives
    reg ack;
    always @(posedge clk_b or negedge rst_n)
        if (!rst_n) begin
            data_out   <= 8'd0;
            data_valid <= 1'b0;
            ack        <= 1'b0;
        end else if (req_sync2 && !ack) begin
            data_out   <= data_hold;  // data is stable because req handshake
            data_valid <= 1'b1;
            ack        <= 1'b1;
        end else begin
            data_valid <= 1'b0;
            if (!req_sync2) ack <= 1'b0;
        end

    // Sync ack: clk_b -> clk_a
    always @(posedge clk_a or negedge rst_n)
        if (!rst_n) begin ack_sync1 <= 0; ack_sync2 <= 0; end
        else        begin ack_sync1 <= ack; ack_sync2 <= ack_sync1; end
endmodule
