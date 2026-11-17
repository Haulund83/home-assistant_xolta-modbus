# What has been verified on a real battery

Rule for this integration: **only features that have been seen working on a real
Xolta site controller become entities or settings.** Everything else stays in the
diagnostics download until someone has seen it work.

Test system: single-phase Xolta battery (48 V pack, 3.6 kW inverter), Modbus
enabled by Ebbefos support in November 2026.

## Reading

| Value | How it was checked |
|---|---|
| State of charge | Matched the cloud (52.66 % vs 52.7 %). |
| Power and its sign | Charge and discharge started from the Ebbefos app: discharge read positive, charge negative, both directions. Matches the cloud's sign but arrives 1–2 min earlier. |
| AC voltage / current (L1) | 235.1 V × 5.61 A ≈ 1.32 kW while power read 1.30 kW. |
| DC voltage / current and sign | 49 V pack; current negative while discharging (-28 A at 1.3 kW), positive while charging. |
| Cell temperature / voltage min-max | Plausible and consistent (3.26–3.31 V, 17–40 °C). |
| Charge / discharge limit | 3.6 kW, the inverter's rating. |
| Grid frequency | 49.93–50.0 Hz. |
| State | Seen as resting (1), starting/stopping (2) and running (3) in step with the battery. |
| Block reads | Input 0..43 and 1000..1003 each read in one request; larger ranges answer exception 2. |

**Energy charged / discharged** are calculated from the verified power value
(trapezoidal integration, gaps over 5 minutes are skipped). The calculation is
covered by tests; compare with your own meter for a few days if you rely on it.

## Control (only with "Allow Home Assistant to control the battery")

| Behaviour | How it was checked |
|---|---|
| Stop (write 0 to holding 1000) | Battery went from -3.5 kW to 0 within ~9 s and stayed at 0 for 5 minutes. |
| Self-consumption (write 1) | Discharged ~1.7 kW and covered the house without export for 8 minutes when repeated every ~20–40 s. Without repetition the cloud resets it after ~90 s. Code 2 is ignored. |
| Auto (stop writing) | The cloud took control back by itself within ~1.5–3 minutes. |

These writes were verified from Home Assistant (YAML Modbus) on the test system.
The integration sends the same writes; its own live run is listed below once done.

| Integration live run | Result |
|---|---|
| Stop via the Override select | pending |
| Self-consumption via the Override select | pending |
| Auto / expiry | pending |

## Connection checks

| Situation | How it was checked |
|---|---|
| Controller present | Answers on TCP 22 and 5900 besides 502. |
| Nothing at the address | All ports time out. |
| Modbus closed | Not seen live (it was already open). Handled as: port 502 refused, or 502 silent while 22/5900 answer. Covered by tests. |

## Not exposed (kept in diagnostics only)

Never seen to change on the test system, or meaning unclear:
fully charged / fully discharged, cell balancing needed, auto cell balancing,
unit state, cluster state, reported Modbus mode (reads 0 even while the cloud
drives the battery), reactive power, AC L2/L3 (single-phase test system).

If your battery shows one of these working, open an issue with a diagnostics
download, and it can be added.
