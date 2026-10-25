import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage } from "../api";
import { rupees } from "./Dashboard";

interface Run {
  id: string;
  period: string;
  created_at: string;
  summary: { counts: Record<string, number>; itc_at_risk: string; matched_itc: string; file?: string } | null;
}

interface Result {
  id: string;
  match_status: string;
  difference_amount: string | null;
  gstr_record: { supplier_gstin: string; invoice_number: string; invoice_value: string } | null;
  invoice_id: string | null;
}

export default function Reconciliation() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  const loadRuns = () => api.get<Run[]>("/reconciliation/runs").then((r) => setRuns(r.data));
  useEffect(() => { loadRuns().catch((e) => setError(errorMessage(e))); }, []);

  useEffect(() => {
    if (!selected) return;
    api.get<Result[]>(`/reconciliation/runs/${selected.id}/results`, { params: filter ? { match_status: filter } : {} })
      .then((r) => setResults(r.data)).catch((e) => setError(errorMessage(e)));
  }, [selected, filter]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    try {
      const { data } = await api.post<Run>("/reconciliation/runs", new FormData(event.currentTarget));
      await loadRuns();
      setSelected(data);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <>
      <h1>GSTR-2B reconciliation</h1>
      <p className="subtitle">Match approved invoices against what your suppliers filed</p>
      <form className="card inline" onSubmit={submit}>
        <label>Period<input name="period" type="month" required /></label>
        <label>GSTR-2B file (.json or .xlsx)<input name="file" type="file" accept=".json,.xlsx" required /></label>
        <button>Reconcile</button>
      </form>
      {error && <p className="error">{error}</p>}
      <table>
        <thead><tr><th>Period</th><th>File</th><th>Matched</th><th>Mismatch</th><th>Missing in GSTR</th><th>Missing in books</th><th>ITC at risk</th></tr></thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="clickable" onClick={() => setSelected(run)}>
              <td>{run.period}</td>
              <td>{run.summary?.file}</td>
              <td>{run.summary?.counts.matched}</td>
              <td>{run.summary?.counts.amount_mismatch}</td>
              <td>{run.summary?.counts.missing_in_gstr}</td>
              <td>{run.summary?.counts.missing_in_books}</td>
              <td>{rupees(run.summary?.itc_at_risk ?? null)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="row">
            <strong>Results for {selected.period}</strong>
            <select style={{ width: 220 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
              {["", "matched", "amount_mismatch", "missing_in_gstr", "missing_in_books"].map((s) => (
                <option key={s} value={s}>{s || "All results"}</option>
              ))}
            </select>
          </div>
          <table>
            <thead><tr><th>Status</th><th>Supplier GSTIN</th><th>Invoice number</th><th>GSTR value</th><th>Difference</th><th /></tr></thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id}>
                  <td><span className={`badge ${r.match_status}`}>{r.match_status.replaceAll("_", " ")}</span></td>
                  <td>{r.gstr_record?.supplier_gstin ?? "—"}</td>
                  <td>{r.gstr_record?.invoice_number ?? "—"}</td>
                  <td>{rupees(r.gstr_record?.invoice_value ?? null)}</td>
                  <td>{rupees(r.difference_amount)}</td>
                  <td>{r.invoice_id && <a href={`/invoices/${r.invoice_id}`}>Invoice</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
