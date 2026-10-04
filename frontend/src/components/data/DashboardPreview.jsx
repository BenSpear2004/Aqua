import React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

const chartColors = ["#55dcf6", "#629dff", "#a1eaff"];

function formatValue(value, type) {
  if (type === "currency") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0
    }).format(value);
  }
  if (type === "percentage") return `${value}%`;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function KpiCards({ kpis }) {
  return (
    <div className="kpi-grid">
      {kpis.map((kpi) => (
        <article className="kpi-card" key={kpi.id}>
          <span>{kpi.label}</span>
          <strong>{formatValue(kpi.value, kpi.type)}</strong>
          {typeof kpi.change === "number" && (
            <small className={kpi.direction === "down" ? "kpi-card__change kpi-card__change--down" : "kpi-card__change"}>
              {kpi.direction === "down" ? "↓" : "↑"} {Math.abs(kpi.change)}% period over period
            </small>
          )}
        </article>
      ))}
    </div>
  );
}

function Chart({ descriptor, table, width, height }) {
  const columnType = table.columns.find((column) => column.key === descriptor.yKey)?.type;
  const xType = table.columns.find((column) => column.key === descriptor.xKey)?.type;
  const common = {
    width,
    height,
    data: table.rows,
    margin: { top: 8, right: 12, left: 4, bottom: 4 }
  };
  const axes = [
      <CartesianGrid key="grid" stroke="rgba(157, 202, 224, .11)" vertical={false} />,
      <XAxis key="x" dataKey={descriptor.xKey} tick={{ fill: "#a9bdcc", fontSize: 11 }} tickLine={false} axisLine={false}
        tickFormatter={(value) => xType === "date" ? new Intl.DateTimeFormat("en-US", { month: "short" }).format(new Date(`${String(value).slice(0, 10)}T12:00:00`)) : value} />,
      <YAxis
        key="y"
        tick={{ fill: "#a9bdcc", fontSize: 11 }}
        tickLine={false}
        axisLine={false}
        width={76}
        tickFormatter={(value) => formatValue(value, columnType)}
      />,
      <Tooltip
        key="tooltip"
        contentStyle={{ background: "#0b2031", border: "1px solid rgba(120,220,255,.24)", borderRadius: 12 }}
        labelStyle={{ color: "#e7f7ff" }}
        formatter={(value) => [formatValue(value, columnType), table.columns.find((column) => column.key === descriptor.yKey)?.label || descriptor.yKey]}
      />
  ];
  const color = chartColors[0];

  if (descriptor.type === "bar") {
    return (
      <BarChart {...common}>
        {axes}
        <Bar dataKey={descriptor.yKey} fill={color} radius={[5, 5, 0, 0]} maxBarSize={42} isAnimationActive={false} />
      </BarChart>
    );
  }
  if (descriptor.type === "line") {
    return (
      <LineChart {...common}>
        {axes}
        <Line type="monotone" dataKey={descriptor.yKey} stroke={color} strokeWidth={2.5} dot={{ r: 3, fill: color }} activeDot={{ r: 5 }} isAnimationActive={false} />
      </LineChart>
    );
  }
  if (descriptor.type === "area") {
    return (
      <AreaChart {...common}>
        {axes}
        <Area type="monotone" dataKey={descriptor.yKey} stroke={color} fill="rgba(56, 213, 245, .17)" strokeWidth={2.5} isAnimationActive={false} />
      </AreaChart>
    );
  }
  return null;
}

export default function DashboardPreview({ visualizations = [], tables = [], kpis = [] }) {
  const previews = visualizations.filter((item) =>
    ["bar", "line", "area", "kpi"].includes(item.type));
  if (kpis.length && !previews.some((item) => item.type === "kpi")) {
    previews.push({ id: "response-metrics", type: "kpi", title: "Key Financial Metrics" });
  }
  if (!previews.length) return null;

  return (
    <section className="dashboard-preview" aria-label="Dashboard Preview">
      <h3>Dashboard Preview</h3>
      <div className="dashboard-preview__grid">
        {previews.map((descriptor) => {
          if (descriptor.type === "kpi") {
            return (
              <article className="chart-card chart-card--kpi" key={descriptor.id}>
                <h4>{descriptor.title || "Key Metrics"}</h4>
                <KpiCards kpis={kpis} />
              </article>
            );
          }
          const table = tables.find((item) => item.id === descriptor.tableId);
          const safeDescriptor = table
            && table.columns.some((column) => column.key === descriptor.xKey)
            && table.columns.some((column) => column.key === descriptor.yKey)
            ? descriptor
            : null;
          return safeDescriptor ? (
            <article className="chart-card" key={descriptor.id}>
              <h4>{descriptor.title}</h4>
              <div className="chart-card__plot" role="img" aria-label={`${descriptor.title || "Financial"} chart`}>
                <ResponsiveContainer width="100%" height="100%">
                  <Chart descriptor={safeDescriptor} table={table} />
                </ResponsiveContainer>
              </div>
            </article>
          ) : null;
        })}
      </div>
    </section>
  );
}
