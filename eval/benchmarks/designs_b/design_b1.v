// Lifecycle controller KMAC interface
// Based on lowRISC/opentitan hw/ip/lc_ctrl/rtl/lc_ctrl_kmac_if.sv
// Based on lowRISC/opentitan lc_ctrl_kmac_if

module lc_ctrl_kmac_if (
    input  wire clk_lc,
    input  wire clk_kmac,
    input  wire rst_n,

    input  wire       kmac_done,
    input  wire       kmac_error,
    input  wire [7:0] kmac_digest,

    input  wire       token_hash_req,
    output reg        token_hash_ack,
    output reg        token_hash_err,
    output reg        fsm_err_o
);

    localparam IDLE = 2'd0, WAIT = 2'd1, DONE = 2'd2, ERROR = 2'd3;
    reg [1:0] state_q, state_d;
    reg       kmac_fsm_err;
    reg [7:0] digest_q;

    always @(posedge clk_kmac or negedge rst_n)
        if (!rst_n) state_q <= IDLE;
        else        state_q <= state_d;

    always @(*) begin
        state_d = state_q;
        kmac_fsm_err = 1'b0;
        case (state_q)
            IDLE:  if (token_hash_req) state_d = WAIT;
            WAIT:  if (kmac_done)      state_d = DONE;
                   else if (kmac_error) state_d = ERROR;
            DONE:  state_d = IDLE;
            ERROR: begin
                kmac_fsm_err = 1'b1;
                state_d = IDLE;
            end
            default: begin
                kmac_fsm_err = 1'b1;
                state_d = ERROR;
            end
        endcase
    end

    always @(posedge clk_kmac or negedge rst_n)
        if (!rst_n) digest_q <= 0;
        else if (kmac_done) digest_q <= kmac_digest;

    reg req_sync1, req_sync2;
    always @(posedge clk_kmac or negedge rst_n)
        if (!rst_n) begin req_sync1 <= 0; req_sync2 <= 0; end
        else        begin req_sync1 <= token_hash_req; req_sync2 <= req_sync1; end

    reg ack_sync1, ack_sync2;
    wire hash_done = (state_q == DONE);
    always @(posedge clk_lc or negedge rst_n)
        if (!rst_n) begin ack_sync1 <= 0; ack_sync2 <= 0; end
        else        begin ack_sync1 <= hash_done; ack_sync2 <= ack_sync1; end

    always @(posedge clk_lc or negedge rst_n)
        if (!rst_n) begin token_hash_ack <= 0; token_hash_err <= 0; end
        else begin
            token_hash_ack <= ack_sync2;
            token_hash_err <= 0;
        end

    assign fsm_err_o = kmac_fsm_err;

endmodule
