function [ok, ref, log] = enrol_corroboration(P, S)
%ENROL_CORROBORATION Bootstrap-verified enrolment (mirror of enrollment.py).
%   Reference is produced only if records corroborate across differing
%   angle/frequency pairings: frequency stability, leave-one-out angle
%   corroboration (2 passes), split-half cross-check, sufficiency.
%   ref.freq, ref.mu_a, ref.sd_a, ref.mu_p, ref.sd_p, ref.angles
log = {};
angles = unique(S.angle)'; freqs = unique(S.freq)';
A = nan(numel(angles), numel(freqs)); Pm = A;
for k = 1:numel(S.amp)
    i = find(angles == S.angle(k)); j = find(freqs == S.freq(k));
    A(i,j) = S.amp(k); Pm(i,j) = S.ph(k);
end
ref = struct(); ok = false;
log{end+1} = sprintf('collected %d records, %d angles, %d freqs', numel(S.amp), numel(angles), numel(freqs));
if numel(angles) < P.min_angles
    log{end+1} = 'REFUSED: too few angles'; return;
end
mad1 = @(X) 1.4826 * nanmed(abs(X - nanmed(X)));
npres = sum(~isnan(A), 1);
sa = zeros(1, numel(freqs)); sp = sa;
for j = 1:numel(freqs), sa(j) = mad1(A(:,j)); sp(j) = mad1(Pm(:,j)); end
fmask = npres >= P.min_angles & sa <= P.max_spread_db & sp <= P.max_spread_deg;
log{end+1} = sprintf('frequency stability: %d/%d usable', sum(fmask), numel(freqs));
if mean(fmask) < P.min_freq_frac
    log{end+1} = 'REFUSED: too few stable frequencies'; return;
end
keep = 1:numel(angles);
for pass = 1:2
    bad = [];
    for i = keep
        others = setdiff(keep, i);
        z = zscore_rows(P, A, Pm, others, i, fmask);
        if mean(z > P.z_max) > P.outlier_frac, bad(end+1) = i; end %#ok<AGROW>
    end
    log{end+1} = sprintf('angle corroboration pass %d: rejected angles [%s]', pass, num2str(angles(bad)));
    keep = setdiff(keep, bad);
    if isempty(bad), break; end
end
if numel(keep) < P.min_angles
    log{end+1} = 'REFUSED: too few corroborating angles'; return;
end
g1 = keep(1:2:end); g2 = keep(2:2:end);
z12 = nanmed(reshape(zscore_rows(P, A, Pm, g1, g2, fmask), [], 1));
z21 = nanmed(reshape(zscore_rows(P, A, Pm, g2, g1, fmask), [], 1));
log{end+1} = sprintf('split-half median z %.2f / %.2f', z12, z21);
if max(z12, z21) > P.z_cross
    log{end+1} = 'REFUSED: split halves disagree'; return;
end
ref.freq = freqs(fmask);
ref.mu_a = nanmean_(A(keep, fmask)); ref.sd_a = nanstd_(A(keep, fmask));
ref.mu_p = nanmean_(Pm(keep, fmask)); ref.sd_p = nanstd_(Pm(keep, fmask));
ref.angles = angles(keep);
ok = true;
log{end+1} = sprintf('CERTIFIED: %d angles, %d freqs -> reference written', numel(keep), sum(fmask));
end

function z = zscore_rows(P, A, Pm, rref, rtest, fmask)
mu_a = nanmean_(A(rref, fmask)); mu_p = nanmean_(Pm(rref, fmask));
if numel(rref) > 1
    sd_a = nanstd_(A(rref, fmask)); sd_p = nanstd_(Pm(rref, fmask));
else
    sd_a = 0 * mu_a; sd_p = 0 * mu_p;
end
za = abs(A(rtest, fmask) - mu_a) ./ hypot(sd_a, P.floor_db);
zp = abs(Pm(rtest, fmask) - mu_p) ./ hypot(sd_p, P.floor_deg);
z = max(za, zp);
end

function m = nanmed(x)
x = x(~isnan(x)); if isempty(x), m = NaN; else, m = median(x); end
end
function m = nanmean_(X)
m = zeros(1, size(X,2));
for j = 1:size(X,2), c = X(~isnan(X(:,j)), j); m(j) = mean(c); end
end
function s = nanstd_(X)
s = zeros(1, size(X,2));
for j = 1:size(X,2), c = X(~isnan(X(:,j)), j); if numel(c) > 1, s(j) = std(c); end, end
end
