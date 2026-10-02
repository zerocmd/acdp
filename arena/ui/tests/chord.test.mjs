import { test } from "node:test";
import assert from "node:assert/strict";
import { chordGeometry, chordLayout } from "../lib/chord.js";

const orgs = [
  { domain: "a.example", organization: "A", agents: [{ id: "x.a.example" }, { id: "y.a.example" }], failed: false },
  { domain: "b.example", organization: "B", agents: [{ id: "z.b.example" }], failed: true },
];

test("arcs are proportional, ordered, and gapped", () => {
  const { arcs } = chordLayout(orgs, 0, 0, 100);
  assert.equal(arcs.length, 2);
  const spanA = arcs[0].end - arcs[0].start;
  const spanB = arcs[1].end - arcs[1].start;
  assert.ok(Math.abs(spanA / spanB - 2) < 1e-9);
  assert.ok(arcs[1].start - arcs[0].end >= 0.04 - 1e-9);
  assert.equal(arcs[1].failed, true);
});

test("anchors sit on the circle", () => {
  const { anchors } = chordLayout(orgs, 10, 20, 100);
  for (const p of Object.values(anchors)) assert.ok(Math.abs(Math.hypot(p.x - 10, p.y - 20) - 100) < 1e-6);
});

test("chordGeometry starts and ends at the anchors", () => {
  const g = chordGeometry({ x: 100, y: 0 }, { x: -100, y: 0 }, { x: 0, y: 0 });
  assert.deepEqual([g.p, g.q], [{ x: 100, y: 0 }, { x: -100, y: 0 }]);
  assert.ok(g.d.startsWith("M100,0 C"));
});
