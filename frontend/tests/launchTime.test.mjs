import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Compile the production helper with the project's existing TypeScript compiler.
const source = readFileSync(new URL("../src/utils/launchTime.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 },
});
const { utcLaunchTimeValue, launchTimeForRequest } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

for (const zone of ["UTC", "Asia/Jerusalem", "America/New_York"]) {
  test(`checked window keeps its exact timestamp in ${zone}`, () => {
    const previous = process.env.TZ;
    process.env.TZ = zone;
    try {
      const checked = "2026-09-21T12:26:54.811735+00:00";
      const value = utcLaunchTimeValue(checked);
      assert.equal(value, "2026-09-21T12:26:54.811");
      assert.equal(launchTimeForRequest(value, checked), checked);
    } finally {
      if (previous === undefined) delete process.env.TZ;
      else process.env.TZ = previous;
    }
  });

  test(`manually entered time is interpreted as UTC in ${zone}`, () => {
    const previous = process.env.TZ;
    process.env.TZ = zone;
    try {
      assert.equal(launchTimeForRequest("2026-09-21T12:26:54", null), "2026-09-21T12:26:54.000Z");
      assert.equal(launchTimeForRequest("2026-09-21T12:26", null), "2026-09-21T12:26:00.000Z");
    } finally {
      if (previous === undefined) delete process.env.TZ;
      else process.env.TZ = previous;
    }
  });
}

test("a manual edit replaces the previously selected window timestamp", () => {
  assert.equal(launchTimeForRequest("2026-09-21T12:27:10", "2026-09-21T12:26:54.811735+00:00"),
    "2026-09-21T12:27:10.000Z");
});

test("a selected offset timestamp displays UTC without changing the checked instant", () => {
  const checked = "2026-09-22T00:00:14.123456+03:00";
  const value = utcLaunchTimeValue(checked);
  assert.equal(value, "2026-09-21T21:00:14.123");
  assert.equal(launchTimeForRequest(value, checked), checked);
});

test("invalid time input cannot become a collision-check timestamp", () => {
  assert.throws(() => launchTimeForRequest("invalid", null), RangeError);
});
