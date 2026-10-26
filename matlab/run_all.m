%RUN_ALL Runs every Assessment-4 MATLAB model in order.
% Requires base MATLAB (R2016b+) or GNU Octave 6+. Toolboxes are not needed
% for these scripts; RF/Stats toolboxes only matter if you extend them.
run_phase0_rehearsal;
pio_fsm_reference;
rc_settling;
run_ablation;
