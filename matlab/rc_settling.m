%RC_SETTLING Settling-time cost of the RC filter between AD8302 and ADS1115.
% Each frequency step needs ~ln(2^16)= 11 tau to settle to 1 LSB of a full-
% scale step; 7 tau (0.1 %) is the firmware default. The trade-off is total
% session time vs residual ripple. Edit R and the plan to match your build.
clear;
R = 10e3;                                   % ohms
C = [10e-9 47e-9 100e-9 220e-9 470e-9 1e-6];
n_tau = 7;
n_freq = 21; n_angles = 8; views = 2;       % plan 0, view A + view B
t_conv = 8 * 2 * 1.2e-3;                    % 8 averages x 2 channels at 860 SPS
tau = R * C;
per_point = n_tau * tau * views + t_conv * views;
session = per_point * n_freq * n_angles;
fc = 1 ./ (2 * pi * tau);
fprintf('   C        tau      fc        settle/pt   RF time per session\n');
for i = 1:numel(C)
    fprintf('%7.0f nF %7.2f ms %8.1f Hz %8.1f ms %10.1f s\n', C(i)*1e9, tau(i)*1e3, fc(i), per_point(i)*1e3, session(i));
end
fprintf('(excludes cradle rotation time; operator dwell dominates in button mode)\n');
