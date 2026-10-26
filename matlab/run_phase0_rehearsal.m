%RUN_PHASE0_REHEARSAL Synthetic 8 vials x 5 angles x 3 repeats x 201 points,
% with thermal noise, ADS1115 quantisation, placement variance and
% temperature drift injected; nested ANOVA; ICC vs frequency.
% Also writes records.csv + sweeps/<record_id>.csv in the agreed layout.
% Synthetic rehearsal only — not evidence about real vials.
clear; rng(0);
P = pgdd_params();
F = numel(P.f_hz);
liq = P.liquids;
AMP = zeros(P.n_vials, P.n_angles, P.n_repeats, F); PH = AMP;
outdir = 'phase0_rehearsal'; if ~exist(fullfile(outdir, 'sweeps'), 'dir'), mkdir(fullfile(outdir, 'sweeps')); end
fid = fopen(fullfile(outdir, 'records.csv'), 'w');
fprintf(fid, 'record_id,vial,liquid,angle,repeat,temp_c,n_avg,noise_mv\n');
rid = 0;
for v = 1:P.n_vials
    L  = liq(mod(v-1, numel(liq)) + 1);
    vk = P.vial_sd * randn(); vq = P.vial_sd * randn();
    for a = 1:P.n_angles
        pk = P.placement_sd * randn(); pph = P.placement_ph_deg * randn();
        for r = 1:P.n_repeats
            T = P.temp_c + P.temp_drift_sd_c * randn();
            [amp, ph] = forward_signature(P, L, P.f_hz, vk, vq, pk, pph, T);
            [mc, pc] = ad8302_transfer(P, amp, ph, true);
            [AMP(v,a,r,:), PH(v,a,r,:)] = codes_to_features(P, mc, pc);
            rid = rid + 1;
            fprintf(fid, '%d,%d,%s,%d,%d,%.2f,%d,%.3f\n', rid, v, L.name, a, r, T, P.n_avg, P.noise_mv);
            g = fopen(fullfile(outdir, 'sweeps', sprintf('%d.csv', rid)), 'w');
            fprintf(g, 'freq_hz,mag_code,phs_code,amplitude_db,phase_deg\n');
            fprintf(g, '%.0f,%d,%d,%.5f,%.4f\n', [P.f_hz; mc; pc; squeeze(AMP(v,a,r,:))'; squeeze(PH(v,a,r,:))']);
            fclose(g);
        end
    end
end
fclose(fid);

Ca = nested_anova_icc(AMP); Cp = nested_anova_icc(PH);
fprintf('amplitude: median ICC %.3f | median SD vial %.3f place %.3f noise %.3f dB\n', ...
    median(Ca.icc), median(sqrt(Ca.s2_vial)), median(sqrt(Ca.s2_place)), median(sqrt(Ca.s2_noise)));
fprintf('phase:     median ICC %.3f | median SD vial %.3f place %.3f noise %.3f deg\n', ...
    median(Cp.icc), median(sqrt(Cp.s2_vial)), median(sqrt(Cp.s2_place)), median(sqrt(Cp.s2_noise)));

fig = figure('Visible', 'off');
subplot(2,1,1);
plot(P.f_hz/1e9, Ca.icc, P.f_hz/1e9, Cp.icc); ylim([0 1.02]); grid on;
ylabel('ICC (vial identity)'); legend('amplitude', 'phase', 'Location', 'southwest');
title('Synthetic Phase 0 rehearsal - not measured data');
subplot(2,1,2);
semilogy(P.f_hz/1e9, sqrt(Ca.s2_vial)+1e-9, P.f_hz/1e9, sqrt(Ca.s2_place)+1e-9, P.f_hz/1e9, sqrt(Ca.s2_noise)+1e-9);
grid on; ylabel('amplitude SD (dB)'); xlabel('frequency (GHz)'); legend('vial', 'placement', 'noise');
print(fig, fullfile(outdir, 'icc_vs_freq.png'), '-dpng', '-r150');
close(fig);
fprintf('wrote %d records to %s/\n', rid, outdir);
