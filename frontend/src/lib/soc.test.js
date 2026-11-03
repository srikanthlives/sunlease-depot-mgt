import { test } from "node:test";
import assert from "node:assert/strict";
import { socTotals, socOf } from "./soc.js";

const trip = (start, end) => ({ trip: { planned_start_soc_pct: start, planned_end_soc_pct: end } });
const charge = (start, end) => ({ charging: { planned_start_soc_pct: start, planned_end_soc_pct: end } });

test("the SOC-bearing part is found whatever the activity is", () => {
  assert.deepEqual(socOf(trip(80, 72)).planned_end_soc_pct, 72);
  assert.equal(socOf({ sequence_number: 1 }), null);
});

test("cycle totals separate what running used from what charging put back", () => {
  const acts = [trip(100, 88), trip(88, 70), charge(70, 95), trip(95, 80)];
  assert.deepEqual(socTotals(acts), { used: 45, gained: 25, net: -20 });
});

test("totals ignore activities with no planned SOC", () => {
  assert.deepEqual(socTotals([trip(80, 72), { layover: {} }, { halt: { start_soc: 60, end_soc: null } }]),
    { used: 8, gained: 0, net: -8 });
  assert.deepEqual(socTotals([]), { used: 0, gained: 0, net: 0 });
});
