import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { AUTH_EXPIRED_EVENT, getToken, initializeAuth, isAuthInitialized, subscribeAuthState } from "./lib/api";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Login from "./pages/Login";
import Report from "./pages/Report";
import Signup from "./pages/Signup";

function Protected({ children }: { children: ReactNode }) {
  const [authReady, setAuthReady] = useState(isAuthInitialized());
  const [token, setToken] = useState(getToken());

  useEffect(() => {
    initializeAuth();
    setAuthReady(true);
    setToken(getToken());
    const unsubscribe = subscribeAuthState(() => {
      setAuthReady(isAuthInitialized());
      setToken(getToken());
    });
    const onExpired = () => setToken("");
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => {
      unsubscribe();
      window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
    };
  }, []);

  if (!authReady) {
    return <main className="grid min-h-screen place-items-center bg-cloud-ink text-slate-100" role="status" aria-live="polite">Restoring session</main>;
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-cloud-ink text-slate-100">
      <Navbar />
      <main className="mx-auto w-full max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/history" element={<Protected><History /></Protected>} />
      <Route path="/report/:analysisId" element={<Protected><Report /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
