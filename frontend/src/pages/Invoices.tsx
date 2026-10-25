import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage, type Invoice, type Page } from "../api";
import { rupees } from "./Dashboard";

const STATUSES = ["", "queued", "processing", "needs_review", "approved", "rejected", "failed"];

export default function Invoices() {
  const navigate = useNavigate();
  const [data, setData] = useState<Page<Invoice> | null>(null);
  const [filters, setFilters] = useState({ status: "", date_from: "", date_to: "", page: 1 });
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    // Only send filters that are set (the API rejects unknown or empty params).
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ""));
    try {
      setData((await api.get<Page<Invoice>>("/invoices", { params: { ...params, page_size: 20 } })).data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [filters]);

  useEffect(() => { load(); }, [load]);

  // Poll every 3 s while any visible invoice is still being processed.
  const inProgress = data?.items.some((i) => i.status === "queued" || i.status === "processing");
  useEffect(() => {
    if (!inProgress) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [inProgress, load]);

  const set = (key: string, value: string | number) => setFilters({ ...filters, [key]: value, page: key === "page" ? Number(value) : 1 });

  return (
    <>
      <h1>Invoices</h1>
      <p className="subtitle">Click an invoice to review, correct and approve it</p>
      <div className="card row">
        <label>Status
          <select value={filters.status} onChange={(e) => set("status", e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s || "All"}</option>)}
          </select>
        </label>
        <label>Invoice date from<input type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} /></label>
        <label>to<input type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} /></label>
      </div>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr><th>File</th><th>Vendor</th><th>Number</th><th>Date</th><th>Total</th><th>Confidence</th><th>Status</th></tr>
        </thead>
        <tbody>
          {data?.items.map((inv) => (
            <tr key={inv.id} className="clickable" onClick={() => navigate(`/invoices/${inv.id}`)}>
              <td>{inv.original_filename}</td>
              <td>{inv.vendor?.name ?? "—"}</td>
              <td>{inv.invoice_number ?? "—"}</td>
              <td>{inv.invoice_date ?? "—"}</td>
              <td>{rupees(inv.total_amount)}</td>
              <td>{inv.confidence_score == null ? "—" : `${Math.round(inv.confidence_score * 100)}%`}</td>
              <td><span className={`badge ${inv.status}`}>{inv.status.replace("_", " ")}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && (
        <div className="row" style={{ marginTop: 12 }}>
          <button className="secondary" disabled={filters.page <= 1} onClick={() => set("page", filters.page - 1)}>Previous</button>
          <span className="muted">Page {data.page} of {Math.max(data.pages, 1)} · {data.total} invoices</span>
          <button className="secondary" disabled={filters.page >= data.pages} onClick={() => set("page", filters.page + 1)}>Next</button>
        </div>
      )}
    </>
  );
}
