import { History, LayoutDashboard, LogOut } from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";
import { cancelPendingRequests, clearAuth, getUserEmail } from "../lib/api";
import { clearStoredActiveAnalysisId } from "../lib/analysisStatus";

export function Navbar() {
  const navigate = useNavigate();
  const email = getUserEmail();

  function logout() {
    cancelPendingRequests();
    clearStoredActiveAnalysisId();
    clearAuth();
    navigate("/login", { replace: true });
  }

  return (
    <header className="border-b border-cloud-line bg-cloud-panel/95">
      <div className="mx-auto flex min-h-16 w-full max-w-6xl items-center justify-between gap-4 px-4">
        <NavLink to="/" className="flex min-w-0 items-center gap-3 font-semibold text-white">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-cloud-line bg-cloud-ink text-cloud-orange">
            $ 
          </span>
          <span className="truncate">BudgetBeagle</span>
        </NavLink>
        <nav className="flex items-center gap-2">
          <NavLink
            to="/"
            aria-label="Dashboard"
            className={({ isActive }) =>
              `inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm ${
                isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`
            }
          >
            <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">Dashboard</span>
          </NavLink>
          <NavLink
            to="/history"
            aria-label="History"
            className={({ isActive }) =>
              `inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm ${
                isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`
            }
          >
            <History className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">History</span>
          </NavLink>
          <span className="hidden max-w-44 truncate text-sm text-slate-400 md:block">{email}</span>
          <button
            type="button"
            onClick={logout}
            className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-cloud-line text-slate-300 hover:border-cloud-orange hover:text-white focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
            aria-label="Sign out"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
          </button>
        </nav>
      </div>
    </header>
  );
}