function S = simulate_session(P, L, vial_k, vial_q, n_angles, f_hz, F, gate_on)
%SIMULATE_SESSION One cradle session through view A/B, faults and the gate.
%   Returns admitted records only: S.angle, S.freq, S.amp, S.ph (N x 1) plus
%   S.n_attempts, S.n_rejected. F = fault struct (see default_faults).
if nargin < 7 || isempty(F), F = default_faults(); end
if nargin < 8, gate_on = true; end
nf = numel(f_hz);
N = n_angles * nf;
S.angle = zeros(N,1); S.freq = zeros(N,1); S.amp = zeros(N,1); S.ph = zeros(N,1);
n = 0; rej = 0;
temp = P.temp_c + F.temp_offset;
for a = 0:n_angles-1
    pk  = P.placement_sd * randn();
    pph = P.placement_ph_deg * randn();
    if any(F.slip_angles == a), pk = pk + F.slip_k; end
    [amp, ph]   = forward_signature(P, L, f_hz, vial_k, vial_q, pk, pph, temp);
    [ampu, phu] = forward_signature(P, L, f_hz + 5e6 + 25e6*rand(), vial_k, vial_q, pk, pph, temp);
    if ~isempty(F.interf_band) && rand() < F.interf_rate
        band = f_hz >= F.interf_band(1) & f_hz <= F.interf_band(2);
        amp = amp + band * F.interf_db;
        ph  = ph + band * F.interf_db * 4;
    end
    for i = 1:nf
        lock = rand() >= F.unlock_rate;
        [ma, pa] = ad8302_transfer(P, amp(i), ph(i));
        if lock, [mb, pb] = ad8302_transfer(P, amp(i), ph(i));
        else,    [mb, pb] = ad8302_transfer(P, ampu(i), phu(i)); end
        if rand() < F.glitch_rate
            mb = mb + sign(rand() - 0.5) * (200 + floor(1800 * rand()));
        end
        if gate_on && ~consistency_gate(P, ma, mb, pa, pb, ~lock)
            rej = rej + 1;
            continue;
        end
        [a1, p1] = codes_to_features(P, ma, pa);
        [a2, p2] = codes_to_features(P, mb, pb);
        n = n + 1;
        S.angle(n) = a; S.freq(n) = f_hz(i);
        S.amp(n) = (a1 + a2) / 2; S.ph(n) = (p1 + p2) / 2;
    end
end
S.angle = S.angle(1:n); S.freq = S.freq(1:n); S.amp = S.amp(1:n); S.ph = S.ph(1:n);
S.n_attempts = N; S.n_rejected = rej;
end
