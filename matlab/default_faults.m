function F = default_faults()
%DEFAULT_FAULTS No-fault configuration; override fields per experiment.
F.glitch_rate = 0;      % transient on one view (gate should reject)
F.unlock_rate = 0;      % PLL unlock: view B off-frequency + poisoned
F.slip_angles = [];     % mis-seated detents (consistent, passes gate)
F.slip_k      = 0.04;
F.interf_band = [];     % [lo hi] Hz, steady interferer (consistent, passes gate)
F.interf_db   = 1.5;
F.interf_rate = 1.0;
F.temp_offset = 0;      % deg C
end
