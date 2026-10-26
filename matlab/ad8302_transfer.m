function [mag_code, phs_code, vmag, vphs] = ad8302_transfer(P, amp_db, ph_deg, add_noise)
%AD8302_TRANSFER Detector transfer + RC-settled output + ADS1115 quantisation.
%   amp_db -> VMAG = 0.9 V + 30 mV/dB ; ph_deg -> VPHS = 1.8 V - 10 mV/deg.
%   Noise: detector/thermal noise averaged over n_avg conversions, then
%   quantised to 62.5 uV codes. Outputs clipped to the 0-1.8 V AD8302 range.
if nargin < 4, add_noise = true; end
vmag = P.vmag_center_v + P.vmag_slope * amp_db;
vphs = P.vphs_zero_v + P.vphs_slope * ph_deg;
vmag = min(1.8, max(0, vmag));
vphs = min(1.8, max(0, vphs));
if add_noise
    sd = P.noise_mv * 1e-3 / sqrt(P.n_avg);
    vmag = vmag + sd * randn(size(vmag));
    vphs = vphs + sd * randn(size(vphs));
end
mag_code = max(-32768, min(32767, round(vmag / P.ads_lsb_v)));
phs_code = max(-32768, min(32767, round(vphs / P.ads_lsb_v)));
end
