function P = pgdd_params()
%PGDD_PARAMS Shared parameters for the Assessment-4 MATLAB models.
%   Mirrors host/pgdd (forward.py, calib.py, gate_model.py, enrollment.py,
%   decide.py) so MATLAB and Python results can be cross-checked.

% --- design of the synthetic dataset (Phase 0 rehearsal)
P.n_vials   = 8;
P.n_angles  = 5;
P.n_repeats = 3;
P.f_hz      = linspace(2.30e9, 2.50e9, 201);

% --- bench / loaded-antenna signature model (synthetic, not validated EM)
P.f0_hz   = 2.62e9;
P.k_fill  = 0.0022;
P.q0      = 18;
P.kq      = 0.004;
P.r_match = 1.25;
P.cable_ns = 0.45;

% --- error sources
P.vial_sd      = 0.02;     % per-vial coupling/Q deviation
P.placement_sd = 0.004;    % per-seat coupling deviation
P.placement_ph_deg = 0.3;
P.noise_mv     = 0.25;     % detector output noise (per conversion)
P.n_avg        = 8;
P.temp_c       = 25;
P.temp_drift_sd_c = 0.5;   % session-to-session

% --- AD8302 (datasheet nominals) and ADS1115 (+-2.048 V)
P.vmag_center_v = 0.900;  P.vmag_slope = 0.030;    % V, V/dB
P.vphs_zero_v   = 1.800;  P.vphs_slope = -0.010;   % V at 0 deg, V/deg
P.ads_lsb_v     = 2.048 / 32768;

% --- trusted comparator (dual grid)
P.mag_bin = 64;  P.phs_bin = 64;

% --- enrolment / arbitration
P.z_max = 3.5;  P.floor_db = 0.05;  P.floor_deg = 0.4;
P.min_angles = 4; P.min_freq_frac = 0.8; P.max_spread_db = 0.6; P.max_spread_deg = 4.0;
P.outlier_frac = 0.25; P.z_cross = 2.0;
P.quorum_frac = 0.6; P.q_min_angles = 3; P.q_min_freqs = 5; P.min_records = 20;

% --- liquids (approximate, for synthesis only): eps_s eps_inf tau_ps alpha sigma
P.liquids = struct( ...
  'name',   {'water','saline_0.9','dextrose_5','ethanol','glycerol_50','prop_glycol'}, ...
  'eps_s',  {78.4, 77.0, 75.5, 24.3, 64.0, 32.0}, ...
  'eps_inf',{5.2, 5.2, 5.0, 4.2, 4.8, 3.5}, ...
  'tau_ps', {8.3, 8.3, 9.4, 163, 27, 60}, ...
  'alpha',  {0, 0, 0, 0.05, 0.1, 0.15}, ...
  'sigma',  {0, 1.6, 0.05, 0, 0, 0});
end
