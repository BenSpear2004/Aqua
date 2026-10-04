import { createMockResponse } from "./mockResponses.js";
import { DEFAULT_MODEL_ID } from "./aiModels.js";

export const FAQS = [
  { id: "largest-expenses", title: "What are my largest expenses?", prompt: "What were my largest expense categories?" },
  { id: "cash-flow-change", title: "How has cash flow changed?", prompt: "Show the monthly cash flow trend." },
  { id: "category-increase", title: "Which costs should I review?", prompt: "Explain in detail which expense categories I should review." },
  { id: "recurring-expenses", title: "Review recurring expenses", prompt: "Show a table of recurring expenses by category." }
];

// Navigation stores references to conversation records, never a second message list.
export const PROJECTS = [
  {
    id: "company-analysis",
    title: "Company Analysis",
    conversationIds: ["expense-analysis", "q3-cash-flow"],
    children: [{ id: "operating-costs", title: "Operating Costs", conversationIds: ["recurring-review"], children: [] }]
  },
  { id: "statements", title: "Statements", conversationIds: ["january-review", "february-review"], children: [] },
  { id: "forecasting", title: "Forecasting", conversationIds: ["2027-budget"], children: [] }
];

const SEEDS = [
  { id: "expense-analysis", title: "Expense Analysis", prompt: "What was our largest expense category?", scenario: "largest expenses" },
  {
    id: "q3-cash-flow", title: "Q3 Cash Flow", prompt: "Show our Q3 cash flow trend.", scenario: "cash flow trend",
    adapt: (response) => ({
      ...response,
      message: "Q3 net cash flow rose from **$92,200 in July** to **$99,950 in September** in this fictional sample.",
      tables: response.tables.map((table) => ({ ...table, title: "Q3 Cash Flow", rows: table.rows.filter((row) => row.month >= "2026-07-01") }))
    })
  },
  {
    id: "january-review", title: "January Review", prompt: "What should I check in the January statement?", scenario: "explain detailed",
    adapt: (response) => ({ ...response, message: "For the **January statement review**, reconcile the opening and closing balances, check recurring charges, and match transfers to their source accounts.\n\nThis conversation is a mock review checklist. No January bank statement has been uploaded." })
  },
  {
    id: "february-review", title: "February Review", prompt: "Find matching transactions in my February statement.", scenario: "no matching",
    adapt: (response) => ({ ...response, message: "No February statement transactions are available in this mock workspace. Add a statement through the future data integration before comparing February with January." })
  },
  {
    id: "2027-budget", title: "2027 Budget", prompt: "Show the key metrics to use as a baseline for the 2027 budget.", scenario: "key metrics",
    adapt: (response) => ({ ...response, message: "Use these **fictional September baseline metrics** to begin the 2027 budget discussion. They describe the sample reporting period; they are not a forecast." })
  },
  {
    id: "recurring-review", title: "Recurring Expense Review", prompt: "Explain how to review our recurring operating expenses.", scenario: "explain detailed",
    adapt: (response) => ({ ...response, message: "Start the recurring expense review with software subscriptions and facility costs. For each charge, confirm the owner, renewal date, usage, and cancellation terms.\n\nCompare those fixed commitments with payroll plans before setting the next operating budget. This is a mock planning checklist." })
  }
];

export function createInitialChatState() {
  const now = Date.now();
  const conversations = SEEDS.map(({ id, title, prompt, scenario, adapt }, index) => {
    const base = createMockResponse(scenario);
    const response = adapt ? adapt(base) : base;
    return {
      id,
      title,
      draft: "",
      updatedAt: now - (index + 1) * 60000,
      request: null,
      messages: [
        { id: `${id}-question`, role: "user", content: prompt, historical: true },
        { id: `${id}-answer`, role: "aqua", response, replyTo: `${id}-question`, historical: true }
      ]
    };
  });
  conversations.unshift({ id: "conversation-start", title: "Ask a Question", draft: "", messages: [], updatedAt: now, request: null });
  return {
    conversations,
    activeConversationId: "conversation-start",
    selectedModelId: DEFAULT_MODEL_ID,
    expandedFolderIds: ["company-analysis", "statements", "forecasting"]
  };
}
