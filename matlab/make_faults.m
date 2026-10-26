function F = make_faults(mode, rate, n_angles)
%MAKE_FAULTS Map (fault mode, corruption rate) to a fault configuration.
F = default_faults();
switch mode
    case 'placement_slip'
        k = round(rate * n_angles);
        F.slip_angles = randperm(n_angles, k) - 1;
    case 'rf_interference'
        F.interf_band = [2.400e9 2.480e9];
        F.interf_rate = min(1, 2 * rate);
    case 'temperature'
        F.temp_offset = 20 * rate;
    case 'transient_glitch'
        F.glitch_rate = rate;
    case 'pll_unlock'
        F.unlock_rate = rate;
    case 'none'
    otherwise
        error('unknown fault mode %s', mode);
end
end
