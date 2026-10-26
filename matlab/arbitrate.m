function [verdict, matched, R] = arbitrate(P, claimed, S, refs, method)
%ARBITRATE Quorum+residual (default) or residual-only decision.
%   refs: struct array with fields id, freq, mu_a, sd_a, mu_p, sd_p
%   verdict: 'CONSISTENT' | 'SUBSTITUTED' | 'DRIFT' | 'INCONCLUSIVE'
if nargin < 5, method = 'quorum'; end
H = numel(refs); N = numel(S.amp);
Z = nan(N, H);
for h = 1:H
    [tf, loc] = ismember(S.freq, refs(h).freq);
    k = find(tf);
    sa = hypot(refs(h).sd_a(loc(k)), P.floor_db);
    sp = hypot(refs(h).sd_p(loc(k)), P.floor_deg);
    Z(k, h) = max(abs(S.amp(k) - refs(h).mu_a(loc(k))') ./ sa', ...
                  abs(S.ph(k)  - refs(h).mu_p(loc(k))') ./ sp');
end
own = find([refs.id] == claimed);
matched = NaN;
if strcmp(method, 'residual')
    R = zeros(1, H);
    for h = 1:H, c = Z(~isnan(Z(:,h)), h); if isempty(c), R(h) = Inf; else, R(h) = mean(c); end, end
    [rmin, w] = min(R);
    if rmin <= P.z_max
        matched = refs(w).id;
        if w == own, verdict = 'CONSISTENT'; else, verdict = 'SUBSTITUTED'; end
    else
        verdict = 'DRIFT';
    end
    return;
end
valid = ~isnan(Z(:, own));
Z = Z(valid, :); ang = S.angle(valid); frq = S.freq(valid); n = sum(valid);
R = inf(1, H);
if n < P.min_records, verdict = 'INCONCLUSIVE'; return; end
for h = 1:H, c = Z(~isnan(Z(:,h)), h); if ~isempty(c), R(h) = median(c); end, end
Zi = Z; Zi(isnan(Zi)) = Inf;
[~, best] = min(Zi, [], 2);
quorate = @(rows) numel(rows) >= P.quorum_frac * n && numel(unique(ang(rows))) >= P.q_min_angles ...
                  && numel(unique(frq(rows))) >= P.q_min_freqs;
[rmin, w] = min(R);
rows_w = find(best == w & Z(:, w) <= P.z_max);
if rmin <= P.z_max && quorate(rows_w)
    matched = refs(w).id;
    if w == own, verdict = 'CONSISTENT'; else, verdict = 'SUBSTITUTED'; end
    return;
end
if quorate(find(Z(:, own) > P.z_max))
    verdict = 'DRIFT';
else
    verdict = 'INCONCLUSIVE';
end
end
