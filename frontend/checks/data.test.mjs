import test from "node:test";
import assert from "node:assert/strict";
import { createCsv, safeCsvCell, formatCell, formatMetric } from "../src/components/data/financialValues.js";

test("CSV preserves delimiters/newlines, protects formulas, and retains negative numbers", () => {
  assert.equal(safeCsvCell('line, "quote"\nnext'), '"line, ""quote""\nnext"');
  assert.equal(safeCsvCell("  =SUM(A1:A2)"), '"\'  =SUM(A1:A2)"');
  assert.equal(safeCsvCell("@SUM(1)"), '"\'@SUM(1)"');
  assert.equal(safeCsvCell(-42.5), '"-42.5"');
  assert.equal(safeCsvCell(null), '""');
  const csv = createCsv({ columns: [{ key: "amount", label: "Amount" }], rows: [{ amount: -9 }] });
  assert.equal(csv, '\uFEFF"Amount"\r\n"-9"');
});

test("financial formatting honors currency metadata and percentage points", () => {
  assert.equal(formatCell(25.5, { type: "currency", currency: "EUR", fractionDigits: 2 }), "€25.50");
  assert.equal(formatCell(48.2, { type: "percentage" }), "48.2%");
  assert.equal(formatCell(null, { type: "number" }), "—");
});

test("headline numbers use the response's currency, dollars otherwise", () => {
  assert.equal(formatMetric(1364203, "currency", "CZK"), "CZK\u00a01,364,203");
  assert.equal(formatMetric(1500, "currency"), "$1,500");
  assert.equal(formatMetric(12.5, "percentage"), "12.5%");
  assert.equal(formatMetric(1234.56, "number"), "1,234.6");
});
