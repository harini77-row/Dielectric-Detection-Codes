// commit_gate.v — behavioural verification model of the commit-gate invariant.
// NOT an FPGA synthesis target and NOT a model of PIO/DMA timing. It states the
// structural property in RTL form so it can be checked by simulation:
//
//     ring_we  ->  consistency(view A, view B)
//
// The ring's write enable is driven only by the comparator's token. There is
// no other write port, so a record that fails the comparison cannot be stored
// and therefore cannot be presented on the read (SPI) side.

module consistency_cmp #(parameter W = 32) (
    input  wire [W-1:0] m0a, m0b, m1a, m1b, p0a, p0b, p1a, p1b,
    output wire         token
);
    assign token = ((m0a == m0b) || (m1a == m1b)) && ((p0a == p0b) || (p1a == p1b));
endmodule

module commit_gate #(parameter W = 32, parameter REC_BITS = 480, parameter SLOTS = 64,
                     parameter AW = 6) (
    input  wire                clk,
    input  wire                rst,
    input  wire                in_valid,           // record builder presents 8 words + body
    input  wire [8*W-1:0]      grid_words,
    input  wire [REC_BITS-1:0] staged_body,
    // read side (host link): only committed slots are addressable
    input  wire [AW-1:0]       rd_idx,
    output wire [REC_BITS-1:0] rd_body,
    output wire                rd_valid,
    output reg  [31:0]         head,
    output wire                ring_we             // exposed for checking
);
    wire token;
    consistency_cmp #(W) cmp (
        .m0a(grid_words[0*W +: W]), .m0b(grid_words[1*W +: W]),
        .m1a(grid_words[2*W +: W]), .m1b(grid_words[3*W +: W]),
        .p0a(grid_words[4*W +: W]), .p0b(grid_words[5*W +: W]),
        .p1a(grid_words[6*W +: W]), .p1b(grid_words[7*W +: W]),
        .token(token));

    reg [REC_BITS-1:0] ring [0:SLOTS-1];
    assign ring_we = in_valid && token;            // the ONLY write enable

    always @(posedge clk) begin
        if (rst) head <= 0;
        else if (ring_we) begin
            ring[head[AW-1:0]] <= staged_body;
            head <= head + 1;
        end
    end

    assign rd_valid = (rd_idx < head);
    assign rd_body  = rd_valid ? ring[rd_idx] : {REC_BITS{1'b0}};
endmodule
