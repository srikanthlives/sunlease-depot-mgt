import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtDate, parseDate, parseTime, fmtDuration, relMin, fmtRel, dirLabel } from "./format.js";

const now = new Date(2026, 9, 21); // 21-Oct-2026

test("formats ISO as DD-MMM-YYYY", () => {
  assert.equal(fmtDate("2026-10-21"), "21-Oct-2026");
  assert.equal(fmtDate("2026-01-05"), "05-Jan-2026");
  assert.equal(fmtDate(null), "");
});

test("parses the accepted date inputs", () => {
  const p = (s, o = {}) => parseDate(s, { now, ...o }).iso;
  assert.equal(p("21-Oct-2026"), "2026-10-21");
  assert.equal(p("21-OCT-26"), "2026-10-21");
  assert.equal(p("21 oct"), "2026-10-21");
  assert.equal(p("21-10-2026"), "2026-10-21");
  assert.equal(p("21/10/26"), "2026-10-21");
  assert.equal(p("21102026"), "2026-10-21");
  assert.equal(p("211026"), "2026-10-21");
  assert.equal(p("0211"), "2026-11-02");
  assert.equal(p("5"), "2026-10-05");
  assert.equal(p("2026-10-21"), "2026-10-21");
  assert.equal(p("T"), "2026-10-21");
  assert.equal(p("+1"), "2026-10-22");
  assert.equal(p("-1", { base: "2026-03-01" }), "2026-02-28");
  assert.equal(p(""), null);
});

test("rejects invalid dates", () => {
  assert.ok(parseDate("31-Feb-2026", { now }).error);
  assert.ok(parseDate("32", { now }).error);
  assert.ok(parseDate("21-Foo-2026", { now }).error);
  assert.ok(parseDate("abc", { now }).error);
});

test("parses times", () => {
  assert.equal(parseTime("930").time, "09:30");
  assert.equal(parseTime("2230").time, "22:30");
  assert.equal(parseTime("9").time, "09:00");
  assert.equal(parseTime("9:5").time, "09:05");
  assert.equal(parseTime("09.30").time, "09:30");
  assert.ok(parseTime("2460").error);
  assert.ok(parseTime("25").error);
  assert.equal(parseTime("").time, null);
});

test("durations use day offsets, not clock times alone", () => {
  assert.equal(relMin(1, "04:30") - relMin(0, "22:30"), 360);
  assert.equal(fmtDuration(360), "6h 00m");
  assert.equal(fmtRel(relMin(1, "04:30")), "04:30 +1");
});

test("a direction reads as its code then its display name", () => {
  assert.equal(dirLabel({ direction_code: "UPSTREAM", direction_name: "Airport to City Centre" }),
    "UPSTREAM · Airport to City Centre");
  assert.equal(dirLabel({ direction_code: "DOWNSTREAM" }), "DOWNSTREAM");   // name missing
  assert.equal(dirLabel({ direction_name: "Airport to City Centre" }), "Airport to City Centre");
  assert.equal(dirLabel(undefined), "");
});
