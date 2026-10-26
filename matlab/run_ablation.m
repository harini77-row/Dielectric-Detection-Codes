%RUN_ABLATION Quorum+residual vs residual-only across 5 injected fault modes,
% swept over corruption rates, several seeds (mean +- SD), gate on and off,
% with confusion matrices per mode.
%
% Figures describe properties of the synthetic corruption generator and the
% forward model, NOT measured system performance.
clear;
P = pgdd_params();
modes = {'placement_slip', 'rf_interference', 'temperature', 'transient_glitch', 'pll_unlock'};
rates = [0 0.1 0.2 0.3];
seeds = 1:5;
n_cont = 6; n_ang = 8;
f_hz = 2.30e9:10e6:2.50e9;
methods = {'quorum', 'residual'};
gates = [true false];
verdicts = {'CONSISTENT', 'SUBSTITUTED', 'DRIFT', 'INCONCLUSIVE'};
truths = {'unchanged', 'substituted'};
% CORRECT(mode, rate, method, gate, seed)
CORRECT = nan(numel(modes), numel(rates), 2, 2, numel(seeds));
CM = zeros(numel(modes), 2, 2, 2, numel(verdicts));   % mode, method, gate, truth, verdict @ max rate

for s = seeds
    rng(s);
    liq = P.liquids;
    for c = 1:n_cont
        cont(c).L = liq(mod(c-1, numel(liq)) + 1); %#ok<SAGROW>
        cont(c).vk = P.vial_sd * randn(); cont(c).vq = P.vial_sd * randn();
        cont(c).id = 100 + c;
    end
    refs = struct('id', {}, 'freq', {}, 'mu_a', {}, 'sd_a', {}, 'mu_p', {}, 'sd_p', {});
    for c = 1:n_cont
        S = simulate_session(P, cont(c).L, cont(c).vk, cont(c).vq, n_ang, f_hz, default_faults(), true);
        [ok, r] = enrol_corroboration(P, S);
        if ok
            refs(end+1) = struct('id', cont(c).id, 'freq', r.freq, 'mu_a', r.mu_a, 'sd_a', r.sd_a, ...
                                 'mu_p', r.mu_p, 'sd_p', r.sd_p); %#ok<SAGROW>
        end
    end
    for mi = 1:numel(modes)
        for ri = 1:numel(rates)
            for gi = 1:2
                hits = zeros(1, 2); tot = 0;
                for c = 1:n_cont
                    if ~any([refs.id] == cont(c).id), continue; end
                    for t = 1:2
                        L = cont(c).L;
                        if t == 2
                            others = liq(~strcmp({liq.name}, L.name));
                            L = others(randi(numel(others)));
                        end
                        F = make_faults(modes{mi}, rates(ri), n_ang);
                        S = simulate_session(P, L, cont(c).vk, cont(c).vq, n_ang, f_hz, F, gates(gi));
                        tot = tot + 1;
                        for me = 1:2
                            v = arbitrate(P, cont(c).id, S, refs, methods{me});
                            good = (t == 1 && strcmp(v, 'CONSISTENT')) || ...
                                   (t == 2 && any(strcmp(v, {'DRIFT', 'SUBSTITUTED'})));
                            hits(me) = hits(me) + good;
                            if ri == numel(rates)
                                vi = find(strcmp(verdicts, v));
                                CM(mi, me, gi, t, vi) = CM(mi, me, gi, t, vi) + 1;
                            end
                        end
                    end
                end
                CORRECT(mi, ri, :, gi, s) = hits / tot;
            end
        end
    end
    fprintf('seed %d done\n', s);
end

M = mean(CORRECT, 5); SD = std(CORRECT, 0, 5);
fig = figure('Visible', 'off', 'Position', [0 0 1400 300]);
styles = {'-o', '--s', ':o', '-.s'};
for mi = 1:numel(modes)
    subplot(1, numel(modes), mi); hold on;
    k = 0;
    for gi = 1:2
        for me = 1:2
            k = k + 1;
            errorbar(rates, M(mi, :, me, gi), SD(mi, :, me, gi), styles{k});
        end
    end
    title(strrep(modes{mi}, '_', ' ')); xlabel('corruption rate'); ylim([0 1.05]); grid on;
    if mi == 1
        ylabel('correct rate (mean \pm SD)');
        legend('quorum, gate on', 'residual, gate on', 'quorum, gate off', 'residual, gate off', 'Location', 'southwest');
    end
end
annotation('textbox', [0 0.95 1 0.05], 'String', ...
    'Synthetic: properties of the corruption generator, not measured performance', ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'center');
print(fig, 'ablation_curves.png', '-dpng', '-r150'); close(fig);

fprintf('\nConfusion matrices at rate %.2f (rows: truth unchanged/substituted; cols: %s)\n', ...
    rates(end), strjoin(verdicts, ' '));
for mi = 1:numel(modes)
    for gi = 1:2
        for me = 1:2
            fprintf('%-17s gate %-3s %-9s  U:[%s]  S:[%s]\n', modes{mi}, mat2str(gates(gi)), methods{me}, ...
                num2str(squeeze(CM(mi, me, gi, 1, :))'), num2str(squeeze(CM(mi, me, gi, 2, :))'));
        end
    end
end
save('ablation_results.mat', 'CORRECT', 'CM', 'modes', 'rates', 'seeds', 'methods', 'verdicts');
