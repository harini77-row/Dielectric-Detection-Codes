function [amp_db, ph_deg, g] = forward_signature(P, L, f_hz, vial_k, vial_q, place_k, place_ph_deg, temp_c)
%FORWARD_SIGNATURE Loaded-antenna reflection -> AD8302 amplitude/phase.
%   Dielectric *signature* generator for synthetic records. It does not and
%   cannot recover permittivity; near-field coupling is deferred to hardware.
if nargin < 8, temp_c = 25; end
e  = cole_cole(f_hz, L, temp_c);
k  = P.k_fill * (1 + vial_k + place_k);
eps_eff = 1 + k * (real(e) - 1);
fr = P.f0_hz ./ sqrt(eps_eff);
inv_q = 1 / (P.q0 * (1 + vial_q)) + P.kq * (k / P.k_fill) * (-imag(e));
q  = 1 ./ inv_q;
z  = P.r_match * (1 + 1i * q .* (f_hz ./ fr - fr ./ f_hz));
g  = (z - 1) ./ (z + 1);
g  = g .* exp(-1i * (2 * pi * f_hz * P.cable_ns * 1e-9 * 2 + deg2rad(place_ph_deg)));
amp_db = min(30, max(-30, 20 * log10(max(abs(g), 1e-4))));
ph_deg = rad2deg(abs(angle(g)));     % AD8302 phase output has no sign
end
