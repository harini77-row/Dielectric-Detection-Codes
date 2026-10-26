function [amp_db, ph_deg] = codes_to_features(P, mag_code, phs_code)
%CODES_TO_FEATURES Inverse detector transfer (host-side calibration).
amp_db = (mag_code * P.ads_lsb_v - P.vmag_center_v) / P.vmag_slope;
ph_deg = min(180, max(0, (phs_code * P.ads_lsb_v - P.vphs_zero_v) / P.vphs_slope));
end
