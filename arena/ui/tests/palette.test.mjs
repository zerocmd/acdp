import { test } from "node:test";
import assert from "node:assert/strict";
import { COMPANY_COLORS, companyColor, THREAD_COLORS, threadColor } from "../palette.js";

test("company colors are stable and from the palette", () => {
  assert.equal(companyColor("northgate.example"), companyColor("northgate.example"));
  assert.ok(COMPANY_COLORS.includes(companyColor("halcyon-inte1.example")));
});

test("thread colors wrap", () => {
  assert.equal(threadColor(THREAD_COLORS.length), THREAD_COLORS[0]);
  assert.equal(threadColor(undefined), THREAD_COLORS[0]);
});
