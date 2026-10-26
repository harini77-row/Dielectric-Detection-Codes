function [tok, w] = consistency_gate(P, ma, mb, pa, pb, poison)
%CONSISTENCY_GATE Bit-exact model of consistency.pio + quantiser.
%   tok = (m0a==m0b | m1a==m1b) & (p0a==p0b | p1a==p1b), on two grids offset
%   by half a bin. Accepts if |A-B| < bin/2, rejects if |A-B| >= bin.
%   poison (lock loss / ADC failure) forces view-B words to differ.
if nargin < 6, poison = false; end
q = @(c, b, off) floor((double(c) + 32768 + off) / b);
mbn = P.mag_bin; pbn = P.phs_bin;
w = [q(ma,mbn,0), q(mb,mbn,0), q(ma,mbn,mbn/2), q(mb,mbn,mbn/2), ...
     q(pa,pbn,0), q(pb,pbn,0), q(pa,pbn,pbn/2), q(pb,pbn,pbn/2)];
if poison
    w([2 4 6 8]) = -1 - w([1 3 5 7]);
end
tok = (w(1) == w(2) || w(3) == w(4)) && (w(5) == w(6) || w(7) == w(8));
end
