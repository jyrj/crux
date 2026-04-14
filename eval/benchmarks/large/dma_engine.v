// DMA engine: sys_clk control + dma_clk data path + usb_clk interface
// Contains handshake crossings, multi-channel control, descriptor FIFOs

module dma_engine (
    input  wire        sys_clk,
    input  wire        dma_clk,
    input  wire        usb_clk,
    input  wire        rst_n,

    // Control interface (sys_clk)
    input  wire [31:0] desc_wdata,
    input  wire        desc_write,
    input  wire [1:0]  channel_sel,
    output wire        dma_done_irq,

    // Data interface (dma_clk)
    output reg  [31:0] mem_wdata,
    output reg         mem_write,

    // USB interface (usb_clk)
    input  wire [7:0]  usb_data_in,
    input  wire        usb_data_valid,
    output reg  [7:0]  usb_data_out
);

    // ---- Channel 0: sys_clk -> dma_clk descriptor transfer (handshake) ----
    reg [31:0] ch0_desc;
    reg        ch0_req;
    reg        ch0_ack_sync1, ch0_ack_sync2;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin ch0_desc <= 0; ch0_req <= 0; end
        else if (desc_write && channel_sel == 0 && !ch0_req) begin
            ch0_desc <= desc_wdata;
            ch0_req <= 1;
        end else if (ch0_ack_sync2) ch0_req <= 0;

    // Sync req to dma_clk
    reg ch0_req_sync1, ch0_req_sync2;
    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) begin ch0_req_sync1 <= 0; ch0_req_sync2 <= 0; end
        else        begin ch0_req_sync1 <= ch0_req; ch0_req_sync2 <= ch0_req_sync1; end

    // DMA side: capture descriptor and execute
    reg ch0_ack;
    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) begin mem_wdata <= 0; mem_write <= 0; ch0_ack <= 0; end
        else if (ch0_req_sync2 && !ch0_ack) begin
            mem_wdata <= ch0_desc;  // stable due to handshake
            mem_write <= 1;
            ch0_ack <= 1;
        end else begin
            mem_write <= 0;
            if (!ch0_req_sync2) ch0_ack <= 0;
        end

    // Sync ack back
    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin ch0_ack_sync1 <= 0; ch0_ack_sync2 <= 0; end
        else        begin ch0_ack_sync1 <= ch0_ack; ch0_ack_sync2 <= ch0_ack_sync1; end

    // ---- Channel 1: sys_clk -> dma_clk (SAFE, same pattern) ----
    reg [31:0] ch1_desc;
    reg        ch1_req, ch1_ack;
    reg        ch1_req_sync1, ch1_req_sync2;
    reg        ch1_ack_sync1, ch1_ack_sync2;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin ch1_desc <= 0; ch1_req <= 0; end
        else if (desc_write && channel_sel == 1 && !ch1_req) begin
            ch1_desc <= desc_wdata; ch1_req <= 1;
        end else if (ch1_ack_sync2) ch1_req <= 0;

    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) begin ch1_req_sync1 <= 0; ch1_req_sync2 <= 0; end
        else        begin ch1_req_sync1 <= ch1_req; ch1_req_sync2 <= ch1_req_sync1; end

    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) ch1_ack <= 0;
        else if (ch1_req_sync2 && !ch1_ack) ch1_ack <= 1;
        else if (!ch1_req_sync2) ch1_ack <= 0;

    always @(posedge sys_clk or negedge rst_n)
        if (!rst_n) begin ch1_ack_sync1 <= 0; ch1_ack_sync2 <= 0; end
        else        begin ch1_ack_sync1 <= ch1_ack; ch1_ack_sync2 <= ch1_ack_sync1; end

    // ---- USB data buffer: usb_clk -> dma_clk (FIFO with gray pointers) ----
    reg [7:0] usb_fifo [0:7];
    reg [3:0] usb_wptr;  // usb_clk
    reg [3:0] usb_rptr;  // dma_clk

    always @(posedge usb_clk or negedge rst_n)
        if (!rst_n) usb_wptr <= 0;
        else if (usb_data_valid) begin
            usb_fifo[usb_wptr[2:0]] <= usb_data_in;
            usb_wptr <= usb_wptr + 1;
        end

    // Gray sync pointers
    wire [3:0] usb_wptr_gray_dma;
    gray_sync #(.W(4)) u_usb_wptr_sync (
        .clk_src_i(usb_clk), .rst_src_ni(rst_n), .bin_i(usb_wptr),
        .clk_dst_i(dma_clk), .rst_dst_ni(rst_n), .gray_o(usb_wptr_gray_dma)
    );

    wire [3:0] usb_rptr_gray_usb;
    gray_sync #(.W(4)) u_usb_rptr_sync (
        .clk_src_i(dma_clk), .rst_src_ni(rst_n), .bin_i(usb_rptr),
        .clk_dst_i(usb_clk), .rst_dst_ni(rst_n), .gray_o(usb_rptr_gray_usb)
    );

    wire usb_fifo_empty = (usb_wptr_gray_dma == usb_rptr[3:0]);
    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) usb_rptr <= 0;
        else if (!usb_fifo_empty) usb_rptr <= usb_rptr + 1;

    // ---- Done IRQ: dma_clk -> sys_clk pulse ----
    reg dma_done_pulse;
    always @(posedge dma_clk or negedge rst_n)
        if (!rst_n) dma_done_pulse <= 0;
        else        dma_done_pulse <= ch0_ack && !ch0_req_sync2;

    pulse_sync u_done_irq (
        .clk_src_i(dma_clk), .rst_src_ni(rst_n), .src_pulse_i(dma_done_pulse),
        .clk_dst_i(sys_clk), .rst_dst_ni(rst_n), .dst_pulse_o(dma_done_irq)
    );

    // ---- USB TX: echo back (usb_clk domain only, no CDC) ----
    always @(posedge usb_clk or negedge rst_n)
        if (!rst_n) usb_data_out <= 0;
        else        usb_data_out <= usb_data_in;
endmodule
