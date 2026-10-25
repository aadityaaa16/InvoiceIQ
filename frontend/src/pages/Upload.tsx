import { useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api";

interface Result {
  name: string;
  id?: string;
  status?: string;
  error?: string;
}

export default function Upload() {
  const [results, setResults] = useState<Result[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);

  // One request per file: each gets its own 202 + id, and one bad file doesn't fail the rest.
  const uploadAll = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    for (const file of Array.from(files)) {
      const body = new FormData();
      body.append("file", file);
      try {
        const { data } = await api.post("/invoices/upload", body);
        setResults((r) => [{ name: file.name, id: data.id, status: data.status }, ...r]);
      } catch (e) {
        setResults((r) => [{ name: file.name, error: errorMessage(e) }, ...r]);
      }
    }
    setBusy(false);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    uploadAll(event.dataTransfer.files);
  };

  return (
    <>
      <h1>Upload invoices</h1>
      <p className="subtitle">Files are processed in the background, usually within seconds</p>
      <label className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)} onDrop={onDrop}>
        <span className="big">{busy ? "⏳" : "📤"}</span>
        <b>{busy ? "Uploading…" : "Drop invoices here"}</b>
        PDF, JPG or PNG · up to 10 MB each · or click to browse
        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" hidden
          onChange={(e) => uploadAll(e.target.files)} />
      </label>
      {results.length > 0 && (
        <table style={{ marginTop: 16 }}>
          <tbody>
            {results.map((r, i) => (
              <tr key={i}>
                <td>{r.name}</td>
                <td>{r.error ? <span className="error">{r.error}</span> : <span className={`badge ${r.status}`}>{r.status}</span>}</td>
                <td>{r.id && <Link to={`/invoices/${r.id}`}>View</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
