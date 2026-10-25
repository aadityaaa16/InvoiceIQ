import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

interface Stats {
  total_invoices: number;
  counts_by_status: Record<string, number>;
  auto_approval_rate: number | null;
  avg_processing_seconds: number | null;
  approved_amount_this_month: string;
}

const STATUS_COLORS: Record<string, string> = {
  queued: "#a5b4fc", processing: "#6366f1", needs_review: "#f59e0b",
  approved: "#22c55e", rejected: "#ef4444", failed: "#94a3b8",
};

export const rupees = (value: string | null) =>
  value == null ? "—" : `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Stats>("/dashboard/stats").then((r) => setStats(r.data)).catch((e) => setError(errorMessage(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!stats) return <p>Loading…</p>;

  const cards: [string, string | number, string, string][] = [
    ["Total invoices", stats.total_invoices, "🧾", "tint-indigo"],
    ["Auto-approval rate", stats.auto_approval_rate == null ? "—" : `${Math.round(stats.auto_approval_rate * 100)}%`, "⚡", "tint-green"],
    ["Avg processing time", stats.avg_processing_seconds == null ? "—" : `${stats.avg_processing_seconds}s`, "⏱️", "tint-amber"],
    ["Approved this month", rupees(stats.approved_amount_this_month), "💰", "tint-pink"],
  ];
  const total = Math.max(stats.total_invoices, 1);

  return (
    <>
      <h1>Dashboard</h1>
      <p className="subtitle">Your invoice pipeline at a glance</p>
      <div className="grid">
        {cards.map(([label, value, icon, tint]) => (
          <div className="card stat-card" key={label}>
            <span className={`stat-icon ${tint}`}>{icon}</span>
            <div>
              <div className="muted">{label}</div>
              <div className="stat">{value}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <strong>Status distribution</strong>
        <div className="dist">
          {Object.entries(stats.counts_by_status).map(([status, count]) => (
            <span key={status} style={{ width: `${(count / total) * 100}%`, background: STATUS_COLORS[status] }} />
          ))}
        </div>
        <div className="legend">
          {Object.entries(stats.counts_by_status).map(([status, count]) => (
            <span key={status}><i style={{ background: STATUS_COLORS[status] }} />{status.replace("_", " ")} · <b>{count}</b></span>
          ))}
        </div>
      </div>
    </>
  );
}
