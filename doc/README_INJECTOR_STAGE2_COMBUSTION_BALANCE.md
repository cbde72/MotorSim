This patch is intended as the next step after:
1) Phase 1 / Phase 2 combined patch
2) injector_stage1_code_patch

What it changes:
- free-piston combustion now performs explicit mass reshuffling based on actual available cylinder fuel vapor and air
- requested heat release is converted to a requested fuel burn rate via qdot/(LHV*eta)
- actual fuel burn rate is limited by:
  - available fuel vapor mass
  - available air mass / AFR_stoich
- air mass is reduced explicitly
- burned mass is increased explicitly
- total gas mass remains unchanged during combustion
- effective qdot is reduced accordingly when fuel/air availability limits combustion

New runtime diagnostics exported in free-piston rows:
- cylinder_combustion_fuel_burn_rate_kg_per_s
- cylinder_combustion_air_consumption_rate_kg_per_s
- cylinder_combustion_burned_production_rate_kg_per_s
- cylinder_combustion_qdot_effective_W

Checked on a composed workspace (base archive + phase1/phase2 + injector stage1):
- compileall successful
- free_piston_GenSet_V09f.yaml with fueling_mode=lambda_from_cylinder_air_at_slot_close_vapor_injector builds successfully
- RHS smoke test returns finite values
