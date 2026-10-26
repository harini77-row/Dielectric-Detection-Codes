// tb_commit_gate.v — randomised check of the commit-gate invariant.
//   iverilog -g2012 -o tb verilog/commit_gate.v verilog/tb_commit_gate.v && vvp tb
`timescale 1ns/1ps
module tb;
    localparam W = 32, RB = 480, SLOTS = 64, AW = 6, N = 20000;
    localparam BIN = 64;

    reg clk = 0, rst = 1, in_valid = 0;
    reg  [8*W-1:0] gw;
    reg  [RB-1:0]  body;
    reg  [AW-1:0]  rd_idx = 0;
    wire [RB-1:0]  rd_body;
    wire rd_valid, ring_we;
    wire [31:0] head;

    commit_gate #(W, RB, SLOTS, AW) dut (clk, rst, in_valid, gw, body, rd_idx, rd_body, rd_valid, head, ring_we);
    always #5 clk = ~clk;

    integer i, accepted, rejected, errors, ma, mb, pa, pb, dm, dp, seed;
    reg expect_tok;
    reg [RB-1:0] golden [0:SLOTS-1];

    function [W-1:0] q(input integer code, input integer off);
        q = (code + 32768 + off) / BIN;
    endfunction

    initial begin
        accepted = 0; rejected = 0; errors = 0; seed = 7;
        repeat (2) @(posedge clk);
        rst = 0;
        for (i = 0; i < N; i = i + 1) begin
            ma = 8000 + ($urandom % 20000);
            pa = ($urandom % 30000);       
            dm = $signed($urandom % 257) - 128;
            dp = $signed($urandom % 257) - 128;
            mb = ma + dm; pb = pa + dp;
            gw = { q(pb, BIN/2), q(pa, BIN/2), q(pb, 0), q(pa, 0),
                   q(mb, BIN/2), q(ma, BIN/2), q(mb, 0), q(ma, 0) };
            body = {$urandom, $urandom, $urandom, i};
            expect_tok = ((q(ma,0) == q(mb,0)) || (q(ma,BIN/2) == q(mb,BIN/2))) &&
                         ((q(pa,0) == q(pb,0)) || (q(pa,BIN/2) == q(pb,BIN/2)));
            in_valid = 1;
            #1;
            // INVARIANT: a write happens iff the consistency predicate holds
            if (ring_we !== expect_tok) begin
                errors = errors + 1;
                $display("FAIL rec %0d: ring_we=%b expected %b (dm=%0d dp=%0d)", i, ring_we, expect_tok, dm, dp);
            end
            // dual-grid guarantees
            if ((dm < BIN/2 && dm > -BIN/2 && dp < BIN/2 && dp > -BIN/2) && !ring_we) errors = errors + 1;
            if ((dm >= BIN || dm <= -BIN || dp >= BIN || dp <= -BIN) && ring_we) errors = errors + 1;
            if (expect_tok) begin golden[head[AW-1:0]] = body; accepted = accepted + 1; end
            else rejected = rejected + 1;
            @(posedge clk); #1;
            in_valid = 0;
            // read side returns exactly what was admitted, and nothing beyond head
            if (head > 0 && head <= SLOTS) begin
                rd_idx = head - 1; #1;
                if (!rd_valid || rd_body !== golden[rd_idx]) errors = errors + 1;
            end
            if (head >= SLOTS) begin               // keep within one ring lap for the check
                @(posedge clk); rst = 1; @(posedge clk); rst = 0;
            end
        end
        rd_idx = head[AW-1:0]; #1;
        if (rd_valid) errors = errors + 1;          // slot at head is never readable
        $display("records %0d: accepted %0d rejected %0d errors %0d", N, accepted, rejected, errors);
        if (errors == 0) $display("PASS: ring_we <-> consistency held on every record");
        else $display("FAIL");
        $finish;
    end
endmodule
