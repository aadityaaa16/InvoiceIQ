import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { errorMessage } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const { user, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const field = (name: string, label: string, type = "text") => (
    <label>
      {label}
      <input type={type} required={name !== "organization_gstin"} value={form[name] ?? ""}
        onChange={(e) => setForm({ ...form, [name]: e.target.value })} />
    </label>
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await login(form.email, form.password);
      else {
        const { organization_gstin, ...rest } = form;
        await register(organization_gstin ? form : rest); // omit empty optional GSTIN
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth-hero">
        <div className="brand" style={{ padding: 0 }}><span className="brand-logo">⚡</span>InvoiceIQ</div>
        <h2>Invoices in. Clean, GST-checked data out.</h2>
        <p>Upload supplier invoices as PDFs or phone photos. AI extracts every field, business rules
          verify it, and GSTR-2B reconciliation shows exactly which tax credit is safe to claim.</p>
        <ul>
          <li>🔍 OCR + LLM extraction with confidence scores</li>
          <li>✅ GSTIN checksum, totals and duplicate checks</li>
          <li>🔁 One-click GSTR-2B reconciliation</li>
        </ul>
      </section>
      <div className="auth-form">
    <form className="card login" onSubmit={submit}>
      <h1>{mode === "login" ? "Welcome back 👋" : "Create your organization"}</h1>
      <p className="subtitle">{mode === "login" ? "Log in to continue to InvoiceIQ" : "Set up your business in under a minute"}</p>
      {mode === "register" && (
        <>
          {field("organization_name", "Business name")}
          {field("organization_gstin", "Business GSTIN (optional)")}
          {field("full_name", "Your name")}
        </>
      )}
      {field("email", "Email", "email")}
      {field("password", "Password", "password")}
      {error && <p className="error">{error}</p>}
      <button disabled={busy} style={{ width: "100%" }}>{mode === "login" ? "Log in" : "Register"}</button>
      <p className="muted">
        <a href="#" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New business? Register" : "Have an account? Log in"}
        </a>
      </p>
    </form>
      </div>
    </div>
  );
}
