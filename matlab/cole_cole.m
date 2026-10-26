function e = cole_cole(f_hz, L, temp_c)
%COLE_COLE Complex relative permittivity (Cole-Cole + ionic conduction).
%   e = cole_cole(f_hz, L, temp_c), L = one element of P.liquids.
%   Simple linear temperature dependence of eps_s and tau (synthetic).
if nargin < 3, temp_c = 25; end
eps0 = 8.854e-12;
dt   = temp_c - 25;
eps_s = L.eps_s * (1 - 0.0046 * dt);
tau   = L.tau_ps * 1e-12 * (1 - 0.02 * dt);
w = 2 * pi * f_hz;
e = L.eps_inf + (eps_s - L.eps_inf) ./ (1 + (1i * w * tau) .^ (1 - L.alpha)) ...
    - 1i * L.sigma ./ (w * eps0);
end
