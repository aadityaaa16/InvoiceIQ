import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, errorMessage, type InvoiceDetail } from "../api";
import { useAuth } from "../auth";
import { rupees } from "./Dashboard";

const FIELDS: [keyof InvoiceDetail | "vendor_gstin" | "vendor_name", string, string][] = [
  ["vendor_name", "Vendor name", "text"],
  ["vendor_gstin", "Vendor GSTIN", "text"],
  ["invoice_number", "Invoice number", "text"],
  ["invoice_date", "Invoice date", "date"],
  ["subtotal", "Subtotal", "number"],
  ["cgst", "CGST", "number"],
  ["sgst", "SGST", "number"],
  ["igst", "IGST", "number"],
  ["total_amount", "Total", "number"],
];

function initialForm(invoice: InvoiceDetail): Record<string, string> {
  return {
    vendor_name: invoice.vendor?.name ?? "",
    vendor_gstin: invoice.vendor?.gstin ?? "",
    invoice_number: invoice.invoice_number ?? "",
    invoice_date: invoice.invoice_date ?? "",
    subtotal: invoice.subtotal ?? "",
    cgst: invoice.cgst ?? "",
    sgst: invoice.sgst ?? "",
    igst: invoice.igst ?? "",
    total_amount: invoice.total_amount ?? "",
  };
}

export default function Review() {
  const { id } = useParams();
  const { user } = useAuth();
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [fileUrl, setFileUrl] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const { data } = await api.get<InvoiceDetail>(`/invoices/${id}`);
    setInvoice(data);
    setForm(initialForm(data));
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(errorMessage(e)));
    api.get(`/invoices/${id}/file`).then((r) => setFileUrl(r.data.url)).catch(() => undefined);
  }, [id, load]);

  // Keep refreshing while the worker is still processing this invoice.
  const processing = invoice?.status === "queued" || invoice?.status === "processing";
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => load().catch(() => undefined), 3000);
    return () => clearInterval(timer);
  }, [processing, load]);

  const act = async (action: () => Promise<unknown>, done: string) => {
    setError("");
    setMessage("");
    try {
      await action();
      await load();
      setMessage(done);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const save = () => {
    // PATCH only what changed; empty inputs mean "clear the field" (null).
    const original = initialForm(invoice!);
    const changes = Object.fromEntries(
      Object.entries(form).filter(([k, v]) => v !== original[k]).map(([k, v]) => [k, v === "" ? null : v]),
    );
    return act(() => api.patch(`/invoices/${id}`, changes), "Saved. Validation re-ran.");
  };

  const reject = () => {
    const reason = window.prompt("Reason for rejection?");
    if (reason) act(() => api.post(`/invoices/${id}/reject`, { reason }), "Rejected.");
  };

  if (error && !invoice) return <p className="error">{error}</p>;
  if (!invoice) return <p>Loading…</p>;

  const canReview = user?.role !== "uploader" && invoice.status === "needs_review";

  return (
    <>
      <h1>
        {invoice.original_filename} <span className={`badge ${invoice.status}`}>{invoice.status.replace("_", " ")}</span>
      </h1>
      <div className="review">
        <div className="card">
          {!fileUrl ? <p className="muted">Loading document…</p>
            : invoice.file_type === "pdf" ? <iframe src={fileUrl} title="Invoice document" />
            : <img src={fileUrl} alt="Invoice document" />}
        </div>
        <div>
          {invoice.failure_reason && <p className="error">{invoice.failure_reason}</p>}
          {!!invoice.validation_errors?.length && (
            <div className="card issues">
              <strong>⚠️ Validation issues</strong>
              <ul>{invoice.validation_errors.map((v, i) => <li key={i}><b>{v.field}</b>: {v.message}</li>)}</ul>
            </div>
          )}
          <div className="card">
            <div className="muted">
              AI confidence: {invoice.confidence_score == null ? "—" : `${Math.round(invoice.confidence_score * 100)}%`}
            </div>
            <div className="confidence"><span style={{ width: `${(invoice.confidence_score ?? 0) * 100}%` }} /></div>
            <div className="field-grid">
            {FIELDS.map(([name, label, type]) => (
              <label key={name}>{label}
                <input type={type} step="0.01" disabled={!canReview} value={form[name] ?? ""}
                  onChange={(e) => setForm({ ...form, [name]: e.target.value })} />
              </label>
            ))}
            </div>
            <strong>Line items</strong>
            <table>
              <tbody>
                {invoice.line_items.map((item) => (
                  <tr key={item.id}><td>{item.description}</td><td>{item.hsn_code}</td><td>{rupees(item.amount)}</td></tr>
                ))}
              </tbody>
            </table>
            {message && <p className="muted">{message}</p>}
            {error && <p className="error">{error}</p>}
            <div className="row" style={{ marginTop: 12 }}>
              {canReview && (
                <>
                  <button onClick={save}>Save corrections</button>
                  <button className="success" onClick={() => act(() => api.post(`/invoices/${id}/approve`), "Approved.")}>Approve</button>
                  <button className="danger" onClick={reject}>Reject</button>
                </>
              )}
              {invoice.status === "failed" && (
                <button onClick={() => act(() => api.post(`/invoices/${id}/retry`), "Re-queued.")}>Retry processing</button>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
