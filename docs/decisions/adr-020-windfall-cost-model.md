# Accurate NSE delivery cost model — side-aware fees + flat DP, no slippage

*Status: accepted · 2026-06-21 · iter-31*

Replaced a flat symmetric bps cost with the real NSE equity-delivery schedule, verified against the Zerodha/Groww calculators: ~11.9 bps buy (STT+stamp+exchange+SEBI+GST) / ~10.4 bps sell + a FLAT Rs15.93 DP per sell, Rs0 brokerage. Slippage dropped (an assumption, not a fee — stressed via the cost-sensitivity 0x/1x/2x card). The flat DP makes returns capital-dependent (small accounts bleed) — intentional realism; costs are read-only in the builder, default capital Rs1L.
