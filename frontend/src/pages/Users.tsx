import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, type Role } from "../api";

interface UserRow {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
}

export default function Users() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState("");

  const load = () => api.get<UserRow[]>("/users").then((r) => setUsers(r.data));
  useEffect(() => { load().catch((e) => setError(errorMessage(e))); }, []);

  const run = async (action: () => Promise<unknown>) => {
    setError("");
    try {
      await action();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const create = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    run(async () => {
      await api.post("/users", Object.fromEntries(new FormData(form)));
      form.reset();
    });
  };

  return (
    <>
      <h1>Users</h1>
      <p className="subtitle">Manage who can upload, review and administer</p>
      <form className="card inline" onSubmit={create}>
        <label>Name<input name="full_name" required /></label>
        <label>Email<input name="email" type="email" required /></label>
        <label>Password<input name="password" type="password" minLength={8} required /></label>
        <label>Role
          <select name="role" defaultValue="uploader">
            <option value="uploader">uploader</option>
            <option value="reviewer">reviewer</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <button>Add user</button>
      </form>
      {error && <p className="error">{error}</p>}
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.full_name}</td>
              <td>{u.email}</td>
              <td>
                <select value={u.role} onChange={(e) => run(() => api.patch(`/users/${u.id}`, { role: e.target.value }))}>
                  <option value="uploader">uploader</option>
                  <option value="reviewer">reviewer</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td>
                <button className={u.is_active ? "secondary" : "success"}
                  onClick={() => run(() => api.patch(`/users/${u.id}`, { is_active: !u.is_active }))}>
                  {u.is_active ? "Deactivate" : "Activate"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
