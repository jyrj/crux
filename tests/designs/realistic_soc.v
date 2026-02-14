// Multi-module SoC: sys_clk, io_clk, aon_clk with mixed sync/unsync crossings

// 2FF Synchronizer primitive (like OpenTitan's prim_flop_2sync)
// ----------
module prim_flop_2sync #(
    parameter WIDTH = 1
) (
    input  wire             clk_i,
    input  wire             rst_ni,
    input  wire [WIDTH-1:0] d_i,
    output reg  [WIDTH-1:0] q_o
);
    reg [WIDTH-1:0] intq;

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            intq <= {WIDTH{1'b0}};
            q_o  <= {WIDTH{1'b0}};
        end else begin
            intq <= d_i;
            q_o  <= intq;
        end
    end
endmodule

// Pulse synchronizer (like OpenTitan's prim_pulse_sync)
// Converts a pulse in src domain to a pulse in dst domain via toggle + 2FF
// ----------
module prim_pulse_sync (
    input  wire clk_src_i,
    input  wire rst_src_ni,
    input  wire src_pulse_i,

    input  wire clk_dst_i,
    input  wire rst_dst_ni,
    output wire dst_pulse_o
);
    // Convert pulse to toggle in source domain
    reg src_level;
    always @(posedge clk_src_i or negedge rst_src_ni) begin
        if (!rst_src_ni)
            src_level <= 1'b0;
        else
            src_level <= src_level ^ src_pulse_i;
    end

    // Synchronize the toggle signal to destination domain
    wire dst_level;
    prim_flop_2sync #(.WIDTH(1)) u_sync (
        .clk_i  (clk_dst_i),
        .rst_ni (rst_dst_ni),
        .d_i    (src_level),
        .q_o    (dst_level)
    );

    // Edge detect: convert toggle back to pulse
    reg dst_level_q;
    always @(posedge clk_dst_i or negedge rst_dst_ni) begin
        if (!rst_dst_ni)
            dst_level_q <= 1'b0;
        else
            dst_level_q <= dst_level;
    end

    assign dst_pulse_o = dst_level_q ^ dst_level;
endmodule

// Status register module (sys_clk domain)
// ----------
module status_reg (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire [7:0]  status_i,
    output reg  [7:0]  status_q
);
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni)
            status_q <= 8'h0;
        else
            status_q <= status_i;
    end
endmodule

// Top-level SoC module
// ----------
module realistic_soc (
    // Clock domains
    input  wire        sys_clk,      // Main system clock (100 MHz)
    input  wire        io_clk,       // IO peripheral clock (24 MHz)
    input  wire        aon_clk,      // Always-on clock (200 KHz)
    input  wire        rst_n,

    // Inputs
    input  wire [7:0]  gpio_in,
    input  wire        uart_rx,
    input  wire        wakeup_event,

    // Outputs
    output wire        uart_tx_sync,
    output wire        wakeup_ack,
    output reg  [7:0]  io_status,
    output reg         aon_flag
);

    // System clock domain registers
    //
    reg uart_tx_req;
    reg [7:0] sys_status;

    always @(posedge sys_clk or negedge rst_n) begin
        if (!rst_n) begin
            uart_tx_req <= 1'b0;
            sys_status  <= 8'h0;
        end else begin
            uart_tx_req <= uart_rx;
            sys_status  <= gpio_in;
        end
    end

    // GOOD: Pulse sync from sys_clk -> io_clk (uart TX request)
    // This uses the prim_pulse_sync module - should be recognized as safe
    //
    prim_pulse_sync u_uart_pulse_sync (
        .clk_src_i   (sys_clk),
        .rst_src_ni  (rst_n),
        .src_pulse_i (uart_tx_req),
        .clk_dst_i   (io_clk),
        .rst_dst_ni  (rst_n),
        .dst_pulse_o (uart_tx_sync)
    );

    // GOOD: 2FF sync from sys_clk -> aon_clk (wakeup event)
    // Direct instantiation of prim_flop_2sync - should be recognized
    //
    wire wakeup_synced;
    prim_flop_2sync #(.WIDTH(1)) u_wakeup_sync (
        .clk_i  (aon_clk),
        .rst_ni (rst_n),
        .d_i    (wakeup_event),
        .q_o    (wakeup_synced)
    );

    reg wakeup_ack_reg;
    always @(posedge aon_clk or negedge rst_n) begin
        if (!rst_n)
            wakeup_ack_reg <= 1'b0;
        else
            wakeup_ack_reg <= wakeup_synced;
    end
    assign wakeup_ack = wakeup_ack_reg;

    // BUG 1: Missing synchronizer - sys_clk -> aon_clk
    // aon_flag driven from sys_clk domain register without sync
    //
    always @(posedge aon_clk or negedge rst_n) begin
        if (!rst_n)
            aon_flag <= 1'b0;
        else
            aon_flag <= sys_status[0];  // VIOLATION: unsynchronized crossing
    end

    // BUG 2: Multi-bit CDC without encoding - sys_clk -> io_clk
    // 8-bit status bus crosses without gray code or handshake
    //
    always @(posedge io_clk or negedge rst_n) begin
        if (!rst_n)
            io_status <= 8'h0;
        else
            io_status <= sys_status;  // VIOLATION: 8-bit bus, no encoding
    end

endmodule
