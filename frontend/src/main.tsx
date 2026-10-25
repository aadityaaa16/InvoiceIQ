import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth, useAuth } from "./auth";
import Dashboard from "./pages/Dashboard";
import Invoices from "./pages/Invoices";
import Login from "./pages/Login";
import Reconciliation from "./pages/Reconciliation";
import Review from "./pages/Review";
import Upload from "./pages/Upload";
import Users from "./pages/Users";
import "./styles.css";

function Layout() {
  const { user, logout } = useAuth();
  const canReview = user?.role !== "uploader";
  const links: [string, string, string, boolean][] = [
    ["/", "📊", "Dashboard", true],
    ["/upload", "⬆️", "Upload", true],
    ["/invoices", "🧾", "Invoices", true],
    ["/reconciliation", "🔁", "Reconciliation", canReview],
    ["/users", "👥", "Users", user?.role === "admin"],
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-logo">⚡</span>InvoiceIQ</div>
        {links.filter(([, , , show]) => show).map(([to, icon, label]) => (
          <NavLink key={to} to={to} end={to === "/"}>
            <span className="icon">{icon}</span>{label}
          </NavLink>
        ))}
        <span className="spacer" />
        <div className="profile">
          <span className="avatar">{user?.full_name.charAt(0).toUpperCase()}</span>
          <span className="who"><b>{user?.full_name}</b><span className="muted">{user?.role} · {user?.organization.name}</span></span>
          <button onClick={logout} title="Log out">⎋</button>
        </div>
      </aside>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/invoices" element={<Invoices />} />
              <Route path="/invoices/:id" element={<Review />} />
              <Route element={<RequireAuth roles={["admin", "reviewer"]} />}>
                <Route path="/reconciliation" element={<Reconciliation />} />
              </Route>
              <Route element={<RequireAuth roles={["admin"]} />}>
                <Route path="/users" element={<Users />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
