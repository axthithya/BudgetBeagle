import { useEffect, useRef, useState } from "react";
import { AlertCircle, Play, RefreshCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ProgressTracker } from "../components/ProgressTracker";
import { apiFetch, getToken, websocketUrl } from "../lib/api";

type RegionsResponse = { regions: string[] };
type GroupsResponse = { resource_groups: { name: string; arn: string; description?: string }[] };
type AnalyzeResponse = { analysis_id: number; status: string; websocket_url: string };

export default function Dashboard() {
  const navigate = useNavigate();
  const socketRef = useRef<WebSocket | null>(null);
  const [regions, setRegions] = useState<string[]>([]);
  const [groups, setGroups] = useState<GroupsResponse["resource_groups"]>([]);
  const [region, setRegion] = useState("");
  const [group, setGroup] = useState("");
  const [messages, setMessages] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    loadRegions();
    return () => socketRef.current?.close();
  }, []);

  useEffect(() => {
    if (region) {
      loadGroups(region);
    }
  }, [region]);

  async function loadRegions() {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<RegionsResponse>("/api/regions");
      setRegions(data.regions);
      setRegion((current) => current || data.regions[0] || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load regions.");
    } finally {
      setLoading(false);
    }
  }

  async function loadGroups(selectedRegion: string) {
    try {
      const data = await apiFetch<GroupsResponse>(`/api/resource-groups?region=${encodeURIComponent(selectedRegion)}`);
      setGroups(data.resource_groups);
      if (!data.resource_groups.some((item) => item.name === group)) {
        setGroup("");
      }
    } catch {
      setGroups([]);
      setGroup("");
    }
  }

  async function runAnalysis() {
    if (!region) return;
    setError("");
    setMessages([]);
    setRunning(true);
    socketRef.current?.close();

    try {
      const data = await apiFetch<AnalyzeResponse>("/api/analyze", {
        method: "POST",
        body: JSON.stringify({ region, resource_group: group || null }),
      });
      const token = encodeURIComponent(getToken());
      const socket = new WebSocket(`${websocketUrl(data.websocket_url)}?token=${token}`);
      socketRef.current = socket;

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as { message: string };
        setMessages((current) => [...current, payload.message]);
        if (payload.message === "Analysis complete") {
          setRunning(false);
          socket.close();
          navigate(`/report/${data.analysis_id}`);
        }
        if (payload.message.startsWith("Analysis failed")) {
          setRunning(false);
        }
      };
      socket.onerror = () => {
        setError("Progress connection failed.");
        setRunning(false);
      };
    } catch (err) {
      setRunning(false);
      setError(err instanceof Error ? err.message : "Analysis could not start.");
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-white">Run Analysis</h1>
            <p className="mt-1 text-sm text-slate-400">AWS account scan</p>
          </div>
          <button
            type="button"
            onClick={loadRegions}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan"
          >
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
            Refresh
          </button>
        </div>

        {error && (
          <div className="mb-5 flex gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-100">
            <AlertCircle className="h-5 w-5 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-300">
            Region
            <select
              className="mt-2 h-11 w-full rounded-md border border-cloud-line bg-cloud-ink px-3 text-white outline-none focus:border-cloud-orange"
              value={region}
              onChange={(event) => setRegion(event.target.value)}
              disabled={loading || running}
            >
              {loading && <option>Loading</option>}
              {!loading && regions.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>

          {groups.length > 0 && (
            <label className="block text-sm font-medium text-slate-300">
              Resource Group
              <select
                className="mt-2 h-11 w-full rounded-md border border-cloud-line bg-cloud-ink px-3 text-white outline-none focus:border-cloud-orange"
                value={group}
                onChange={(event) => setGroup(event.target.value)}
                disabled={running}
              >
                <option value="">Whole region</option>
                {groups.map((item) => <option key={item.arn || item.name} value={item.name}>{item.name}</option>)}
              </select>
            </label>
          )}
        </div>

        <button
          type="button"
          onClick={runAnalysis}
          disabled={!region || loading || running}
          className="mt-6 inline-flex h-11 items-center gap-2 rounded-md bg-cloud-orange px-5 font-semibold text-slate-950 hover:bg-orange-300 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Play className="h-4 w-4" aria-hidden="true" />
          {running ? "Running" : "Run Analysis"}
        </button>
      </section>

      <aside>
        <h2 className="mb-3 text-sm font-semibold uppercase text-slate-400">Progress</h2>
        <ProgressTracker messages={messages} />
      </aside>
    </div>
  );
}