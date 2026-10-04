const expenseTable = {
  id: "expenses-by-category",
  title: "Expenses by Category",
  columns: [
    { key: "category", label: "Category", type: "string" },
    { key: "amount", label: "Amount", type: "currency" },
    { key: "percentage", label: "% of Total", type: "percentage" },
    { key: "period", label: "Period", type: "date" }
  ],
  rows: [
    { category: "Payroll", amount: 184200, percentage: 48.2, period: "2026-09-30" },
    { category: "Rent", amount: 62400, percentage: 16.3, period: "2026-09-30" },
    { category: "Software", amount: 38120, percentage: 10, period: "2026-09-30" },
    { category: "Marketing", amount: 27650, percentage: 7.2, period: "2026-09-30" },
    { category: "Other", amount: 69780, percentage: 18.3, period: "2026-09-30" }
  ]
};

const monthlyTable = {
  id: "monthly-cash-flow",
  title: "Monthly Cash Flow",
  columns: [
    { key: "month", label: "Month", type: "date" },
    { key: "income", label: "Income", type: "currency" },
    { key: "expenses", label: "Expenses", type: "currency" },
    { key: "net", label: "Net Cash Flow", type: "currency" }
  ],
  rows: [
    { month: "2026-04-30", income: 412000, expenses: 338000, net: 74000 },
    { month: "2026-05-31", income: 428500, expenses: 351200, net: 77300 },
    { month: "2026-06-30", income: 405300, expenses: 342700, net: 62600 },
    { month: "2026-07-31", income: 451800, expenses: 359600, net: 92200 },
    { month: "2026-08-31", income: 466400, expenses: 371500, net: 94900 },
    { month: "2026-09-30", income: 482100, expenses: 382150, net: 99950 }
  ]
};

const baseResponse = {
  status: "success",
  tables: [],
  visualizations: [],
  kpis: []
};

export function createMockResponse(prompt) {
  const query = prompt.toLowerCase();

  if (/\b(error|fail|retry)\b/.test(query)) {
    return {
      status: "error",
      error: {
        code: "mock_unavailable",
        message: "AQUA couldn't complete that request. Please try again.",
        retryable: true
      }
    };
  }

  if (/\b(no data|no matching|not found|empty results)\b/.test(query)) {
    return {
      ...baseResponse,
      message: "No matching financial data was found for that request."
    };
  }

  if (/\b(long|explain|detailed)\b/.test(query)) {
    return {
      ...baseResponse,
      message:
        "Your operating expenses remained concentrated in a few predictable areas over the latest reporting period.\n\nPayroll was the largest category, representing **48.2%** of recorded expenses. Rent and software followed. Together, these three categories account for 74.5% of the total shown below.\n\nA consistent review of recurring software subscriptions and hiring plans may help explain changes in these costs over time."
    };
  }

  if (/\b(multiple|both|two tables)\b/.test(query)) {
    return {
      ...baseResponse,
      message: "Here is a category-level view alongside the recent cash-flow trend.",
      tables: [expenseTable, monthlyTable],
      visualizations: [
        { id: "expense-bars", type: "bar", title: "Expenses by Category", tableId: expenseTable.id, xKey: "category", yKey: "amount" },
        { id: "cash-flow-area", type: "area", title: "Monthly Net Cash Flow", tableId: monthlyTable.id, xKey: "month", yKey: "net" }
      ],
      kpis: [
        { id: "monthly-income", label: "September income", value: 482100, type: "currency", change: 3.4, direction: "up" },
        { id: "monthly-expenses", label: "September expenses", value: 382150, type: "currency", change: 2.9, direction: "up" },
        { id: "net-margin", label: "Net margin", value: 20.7, type: "percentage", change: 0.4, direction: "up" }
      ]
    };
  }

  if (/\b(line|trend|cash flow)\b/.test(query)) {
    return {
      ...baseResponse,
      message: "Net cash flow increased across the last three months shown.",
      tables: [monthlyTable],
      visualizations: [
        { id: "cash-flow-line", type: "line", title: "Monthly Net Cash Flow", tableId: monthlyTable.id, xKey: "month", yKey: "net" }
      ]
    };
  }

  if (/\b(area)\b/.test(query)) {
    return {
      ...baseResponse,
      message: "Here is a six-month view of income and expenses.",
      tables: [monthlyTable],
      visualizations: [
        { id: "income-area", type: "area", title: "Income Over Time", tableId: monthlyTable.id, xKey: "month", yKey: "income" }
      ]
    };
  }

  if (/\b(kpi|metrics|key metrics)\b/.test(query)) {
    return {
      ...baseResponse,
      message: "Here are the latest headline figures for the reporting period.",
      visualizations: [{ id: "headline-kpis", type: "kpi", title: "Key Financial Metrics" }],
      kpis: [
        { id: "income", label: "Total income", value: 482100, type: "currency", change: 3.4, direction: "up" },
        { id: "expenses", label: "Total expenses", value: 382150, type: "currency", change: 2.9, direction: "up" },
        { id: "net", label: "Net cash flow", value: 99950, type: "currency", change: 5.3, direction: "up" }
      ]
    };
  }

  if (/\b(table|csv|export|expenses|expense|category|categories|bar chart|largest)\b/.test(query)) {
    return {
      ...baseResponse,
      message: "Payroll was your largest expense category in the latest reporting period.",
      tables: [expenseTable],
      visualizations: [
        { id: "expense-bars", type: "bar", title: "Expenses by Category", tableId: expenseTable.id, xKey: "category", yKey: "amount" }
      ]
    };
  }

  return {
    ...baseResponse,
    message: "I can help you explore financial performance, expenses, and cash flow. Try asking for a breakdown by category, a monthly trend, or key financial metrics."
  };
}
