import { soc } from "./format.js";

/** The SOC-bearing part of an activity, whichever kind it is. */
export const socOf = (a) => (a ? a.trip || a.movement || a.charging || a.halt || a.layover || null : null);

/** SOC used (sum of the drops) and gained (sum of the rises) across a list of activities. */
export function socTotals(activities) {
  let used = 0;
  let gained = 0;
  for (const a of activities || []) {
    const s = soc(socOf(a));
    if (!s || s.delta === null) continue;
    if (s.delta < 0) used -= s.delta;
    else gained += s.delta;
  }
  const r = (x) => Math.round(x * 100) / 100;
  return { used: r(used), gained: r(gained), net: r(gained - used) };
}
