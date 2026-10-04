export function formatCell(value, column, table = {}) {
  if (value == null) return "\u2014";
  if (column.type === "currency" && typeof value === "number") {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: column.currency || table.currency || "USD",
      maximumFractionDigits: column.fractionDigits ?? 0
    }).format(value);
  }
  if (column.type === "percentage" && typeof value === "number") {
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)}%`;
  }
  if (column.type === "number" && typeof value === "number") {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  }
  if (column.type === "date" && typeof value === "string") {
    const date = new Date(`${value.slice(0, 10)}T12:00:00`);
    return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", year: "numeric"
    }).format(date);
  }
  return String(value);
}

export function safeCsvCell(value) {
  const text = value == null ? "" : String(value);
  // Preserve real negative numbers. Protect spreadsheet-sensitive text in any column.
  const safe = typeof value === "string" && /^[\s]*[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function createCsv(table, rows = table.rows) {
  return `\uFEFF${[
    table.columns.map((column) => safeCsvCell(column.label)).join(","),
    ...rows.map((row) => table.columns.map((column) => safeCsvCell(row[column.key])).join(","))
  ].join("\r\n")}`;
}
