function C = nested_anova_icc(Y)
%NESTED_ANOVA_ICC Balanced nested ANOVA, Y(vial, placement, repeat, freq).
%   C.s2_vial, C.s2_place, C.s2_noise, C.icc (1 x F). Same estimator as
%   phase0/variance_decomp.py so the VNA analysis can be cross-checked.
[V, P, R, F] = size(Y);
gm = mean(mean(mean(Y, 1), 2), 3);                  % 1x1x1xF
vm = mean(mean(Y, 2), 3);                           % Vx1x1xF
pm = mean(Y, 3);                                    % VxPx1xF
ss_v = P * R * squeeze(sum((vm - gm).^2, 1))';
ss_p = R * squeeze(sum(sum((pm - vm).^2, 1), 2))';
ss_r = squeeze(sum(sum(sum((Y - pm).^2, 1), 2), 3))';
ms_v = ss_v / (V - 1);
ms_p = ss_p / (V * (P - 1));
ms_r = ss_r / (V * P * (R - 1));
C.s2_noise = ms_r;
C.s2_place = max(0, (ms_p - ms_r) / R);
C.s2_vial  = max(0, (ms_v - ms_p) / (P * R));
C.icc = C.s2_vial ./ (C.s2_vial + C.s2_place + C.s2_noise);
end
