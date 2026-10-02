import { test } from "node:test";
import assert from "node:assert/strict";
import { bandOf, capQueue, freshEvents, groupOrgs, layoutMap, placePopup, pointOnCubic,
  ribbonGeometry, ribbonWidth } from "../lib/commsmap.js";

const ag = (id, sector, status = "verified") => ({ id, domain: id.split(".").slice(1).join("."),
  organization: id.split(".")[1], sector, status });
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test("bandOf defaults unknown sectors to provider", () => {
  assert.equal(bandOf("member"), "member");
  assert.equal(bandOf(undefined), "provider");
  assert.equal(bandOf("vendor"), "provider");
});

test("groupOrgs groups by domain and flags all-failed organizations", () => {
  const orgs = groupOrgs([ag("a.n.example", "member"), ag("b.n.example", "member"),
    ag("c.fake.example", "provider", "failed")]);
  assert.deepEqual(orgs.map((o) => [o.domain, o.agents.length, o.failed]),
    [["n.example", 2, false], ["fake.example", 1, true]]);
});

test("layout fits narrow widths without overlap", () => {
  const agents = [];
  for (let i = 0; i < 34; i += 1) agents.push(ag(`a${i}.org${i % 17}.example`, ["member", "provider", "assurance"][i % 3]));
  for (const width of [900, 1600]) {
    const m = layoutMap(agents, width);
    assert.equal(m.bands.length, 3);
    for (const o of m.orgs) {
      assert.ok(o.x >= 0 && o.x + o.w <= width + 0.001, `x in bounds at ${width}`);
    }
    for (let i = 0; i < m.orgs.length; i += 1) {
      for (let j = i + 1; j < m.orgs.length; j += 1) assert.ok(!overlap(m.orgs[i], m.orgs[j]));
    }
    for (const a of agents) assert.ok(m.nodes[a.id], a.id);
  }
});

test("failed organizations sort to the end of their band", () => {
  const m = layoutMap([ag("x.bad.example", "provider", "failed"), ag("y.good.example", "provider")], 1200);
  const [first, second] = m.orgs.filter((o) => o.band === "provider");
  assert.equal(first.domain, "good.example");
  assert.equal(second.domain, "bad.example");
});

test("ribbon width follows the log rule and caps at 18", () => {
  assert.equal(ribbonWidth(1), 6);
  assert.equal(ribbonWidth(3), 10);
  assert.equal(ribbonWidth(1000), 18);
});

test("ribbon geometry: midpoint on the curve, same-column loops bulge right", () => {
  const nodes = { a: { x: 100, y: 100 }, b: { x: 500, y: 300 }, c: { x: 110, y: 400 } };
  const g = ribbonGeometry({ source: "a", target: "b", curvature: 0 }, nodes);
  assert.deepEqual(g.mid, pointOnCubic(g.p, g.c1, g.c2, g.q, 0.5));
  assert.ok(g.d.startsWith("M100,100 C"));
  const loop = ribbonGeometry({ source: "a", target: "c", curvature: 0 }, nodes);
  assert.ok(loop.c1.x > 150 && loop.c2.x > 150);
  const shifted = ribbonGeometry({ source: "a", target: "b", curvature: 0.25 }, nodes);
  assert.notDeepEqual(shifted.mid, g.mid);
});

test("pointOnCubic endpoints", () => {
  const p = { x: 0, y: 0 }; const q = { x: 10, y: 10 };
  assert.deepEqual(pointOnCubic(p, p, q, q, 0), p);
  assert.deepEqual(pointOnCubic(p, p, q, q, 1), q);
});

test("placePopup avoids active popups and stays in bounds", () => {
  const size = { w: 240, h: 64 };
  const bounds = { w: 1000, h: 800 };
  const active = [];
  for (let i = 0; i < 3; i += 1) active.push({ ...placePopup(active, { x: 500, y: 300 }, size, bounds), ...size });
  for (let i = 0; i < 3; i += 1) for (let j = i + 1; j < 3; j += 1) assert.ok(!overlap(active[i], active[j]));
  const edge = placePopup([], { x: 990, y: 5 }, size, bounds);
  assert.ok(edge.x + size.w <= bounds.w && edge.y >= 0);
});

test("freshEvents ignores events at or below the mount seq", () => {
  assert.deepEqual(freshEvents([{ seq: 4 }, { seq: 5 }, { seq: 6 }], 5).map((e) => e.seq), [6]);
});

test("pulse queue caps at 20 and drops the oldest", () => {
  let q = [];
  for (let i = 0; i < 25; i += 1) q = capQueue(q, { id: i }, 20);
  assert.equal(q.length, 20);
  assert.equal(q[0].id, 5);
});
