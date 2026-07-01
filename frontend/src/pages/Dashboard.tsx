import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, Copy, Check, Play, RefreshCcw, Search, Shield, ShieldAlert, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ProgressTracker } from "../components/ProgressTracker";
import { apiFetch, AwsStatus, getToken, websocketUrl } from "../lib/api";
import { clearStoredActiveAnalysisId, getStoredActiveAnalysisId, isFailureAnalysisStatus, isSuccessfulAnalysisStatus, isTerminalAnalysisStatus, storeActiveAnalysisId } from "../lib/analysisStatus";

type RegionMode = "single_region" | "selected_regions" | "all_enabled_regions";
type RegionsResponse = { regions: string[]; status?: "available" | "empty" | "permission_denied" | "unavailable" | string; error?: { code?: string; message?: string; category?: string; permission?: string } | null; permission?: string };
type GroupsResponse = { resource_groups: { name: string; arn: string; description?: string }[] };
type AnalyzeResponse = { analysis_id: number; status: string; websocket_url: string };
type AnalysisLookupResponse = { analysis: { status: string; analysis_result?: { error?: string; reason?: string } } };
type ProgressDetails = { reason?: string; region_mode?: RegionMode | string; total_region_count?: number; completed_region_count?: number; failed_region_count?: number; active_regions?: string[]; current_service?: string; resources_discovered?: number; findings_generated?: number; warning_count?: number; cancellation_state?: string; overall_percentage?: number };
type ProgressPayload = { event?: string; message?: string; status?: string; details?: ProgressDetails };
const REGION_PATTERN = /^(?:[a-z]{2}|cn|us-gov|us-iso|us-isob|us-isof)-[a-z0-9-]+-\d+$/;

const MINIMAL_POLICY = JSON.stringify({
  Version: "2012-10-17",
  Statement: [{
    Effect: "Allow",
    Action: [
      "sts:GetCallerIdentity",
      "ec2:DescribeInstances", "ec2:DescribeVolumes", "ec2:DescribeAddresses",
      "ec2:DescribeNatGateways", "ec2:DescribeRegions",
      "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTags",
      "rds:DescribeDBInstances", "rds:ListTagsForResource",
      "s3:ListAllMyBuckets", "s3:GetBucketLocation",
      "cloudwatch:GetMetricStatistics", "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
      "resource-groups:ListGroups", "resource-groups:ListGroupResources",
      "tag:GetResources",
    ],
    Resource: "*",
  }],
}, null, 2);

const EXTENDED_POLICY = JSON.stringify({
  Version: "2012-10-17",
  Statement: [
    {
      Sid: "BudgetBeagleCoreScan",
      Effect: "Allow",
      Action: [
        "sts:GetCallerIdentity",
        "ec2:DescribeInstances", "ec2:DescribeVolumes", "ec2:DescribeAddresses",
        "ec2:DescribeNatGateways", "ec2:DescribeRegions",
        "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTags",
        "rds:DescribeDBInstances", "rds:ListTagsForResource",
        "s3:ListAllMyBuckets", "s3:GetBucketLocation",
        "cloudwatch:GetMetricStatistics", "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
        "resource-groups:ListGroups", "resource-groups:ListGroupResources",
        "tag:GetResources",
      ],
      Resource: "*",
    },
    {
      Sid: "BudgetBeagleOptionalEnrichment",
      Effect: "Allow",
      Action: ["s3:GetLifecycleConfiguration", "ce:GetCostAndUsage"],
      Resource: "*",
    },
  ],
}, null, 2);

export default function Dashboard() {
  const navigate = useNavigate();
  const socketRef = useRef<WebSocket | null>(null);
  const pollingTimerRef = useRef<number | null>(null);
  const activeAnalysisIdRef = useRef<number | null>(null);
  const navigatedAnalysisIdsRef = useRef<Set<number>>(new Set());
  const initialLoadStartedRef = useRef(false);
  const [regions, setRegions] = useState<string[]>([]);
  const [groups, setGroups] = useState<GroupsResponse["resource_groups"]>([]);
  const [region, setRegion] = useState("");
  const [group, setGroup] = useState("");
  const [messages, setMessages] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [awsStatus, setAwsStatus] = useState<AwsStatus | null>(null);
  const [showPolicyModal, setShowPolicyModal] = useState(false);
  const [policyCopied, setPolicyCopied] = useState(false);
  const [currentAnalysisId, setCurrentAnalysisId] = useState<number | null>(null);
  const [regionMode, setRegionMode] = useState<RegionMode>("single_region");
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
  const [regionFilter, setRegionFilter] = useState("");
  const [regionDiscoveryStatus, setRegionDiscoveryStatus] = useState<RegionsResponse["status"]>("unavailable");
  const [regionDiscoveryError, setRegionDiscoveryError] = useState<RegionsResponse["error"] | null>(null);
  const [progressDetails, setProgressDetails] = useState<ProgressDetails | null>(null);

  useEffect(() => {
    if (!initialLoadStartedRef.current) {
      initialLoadStartedRef.current = true;
      loadRegions();
      loadAwsStatus();
      const storedAnalysisId = getStoredActiveAnalysisId();
      if (storedAnalysisId) {
        setMessages(["Recovering active analysis..."]);
        startPolling(storedAnalysisId);
      }
    }
    return () => {
      stopPolling();
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (region && regionMode === "single_region") {
      loadGroups(region);
    } else {
      setGroups([]);
      setGroup("");
    }
  }, [region, regionMode]);

  async function loadRegions() {
    setLoading(true);
    setError("");
    setRegionDiscoveryError(null);
    try {
      const data = await apiFetch<RegionsResponse>("/api/regions");
      const sorted = [...new Set(data.regions)].filter(isValidRegion).sort();
      setRegions(sorted);
      setRegionDiscoveryStatus(data.status ?? (sorted.length ? "available" : "empty"));
      setRegionDiscoveryError(data.error ?? null);
      setRegion((current) => current || sorted[0] || "");
      setSelectedRegions((current) => {
        const kept = current.filter((item) => sorted.includes(item));
        if (kept.length) return kept;
        return sorted[0] ? [sorted[0]] : [];
      });
    } catch (err) {
      setRegions([]);
      setSelectedRegions([]);
      setRegionDiscoveryStatus("unavailable");
      setRegionDiscoveryError({ message: err instanceof Error ? err.message : "Could not load regions." });
      setError(err instanceof Error ? err.message : "Could not load regions.");
    } finally {
      setLoading(false);
    }
  }
  async function loadAwsStatus() {
    try {
      const data = await apiFetch<AwsStatus>("/api/aws/status");
      setAwsStatus(data);
    } catch {
      // Non-critical - don't block the UI
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

  function appendMessage(message: string) {
    setMessages((current) => (current[current.length - 1] === message ? current : [...current, message]));
  }

  function stopPolling() {
    if (pollingTimerRef.current !== null) {
      window.clearTimeout(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  }

  function finishAnalysis(analysisId?: number) {
    stopPolling();
    if (analysisId === undefined || activeAnalysisIdRef.current === analysisId) {
      activeAnalysisIdRef.current = null;
    }
    clearStoredActiveAnalysisId(analysisId);
    setRunning(false);
    setCurrentAnalysisId((current) => (analysisId === undefined || current === analysisId ? null : current));
    if (socketRef.current) {
      const socket = socketRef.current;
      socketRef.current = null;
      socket.close();
    }
  }

  function navigateToReportOnce(analysisId: number) {
    if (navigatedAnalysisIdsRef.current.has(analysisId)) return;
    navigatedAnalysisIdsRef.current.add(analysisId);
    navigate(`/report/${analysisId}`);
  }

  async function pollAnalysis(analysisId: number) {
    if (activeAnalysisIdRef.current !== analysisId) return;
    try {
      const res = await apiFetch<AnalysisLookupResponse>(`/api/analyses/${analysisId}`);
      const status = res.analysis.status;
      if (isSuccessfulAnalysisStatus(status)) {
        appendMessage("Analysis complete");
        finishAnalysis(analysisId);
        navigateToReportOnce(analysisId);
        return;
      }
      if (isFailureAnalysisStatus(status)) {
        const reason = res.analysis.analysis_result?.reason ?? res.analysis.analysis_result?.error;
        appendMessage(reason ?? `Analysis ${status}.`);
        finishAnalysis(analysisId);
        return;
      }
      if (isTerminalAnalysisStatus(status)) {
        finishAnalysis(analysisId);
        return;
      }
      startPolling(analysisId, 2000);
    } catch (err) {
      finishAnalysis(analysisId);
      setError("Polling failed: " + (err instanceof Error ? err.message : String(err)));
    }
  }

  function startPolling(analysisId: number, delayMs = 0) {
    stopPolling();
    activeAnalysisIdRef.current = analysisId;
    storeActiveAnalysisId(analysisId);
    setCurrentAnalysisId(analysisId);
    setRunning(true);
    const run = () => void pollAnalysis(analysisId);
    if (delayMs <= 0) {
      run();
    } else {
      pollingTimerRef.current = window.setTimeout(run, delayMs);
    }
  }

  async function runAnalysis() {
    const validation = scanValidationError();
    if (validation) {
      setError(validation);
      return;
    }
    setError("");
    setMessages([]);
    setProgressDetails(null);
    setRunning(true);
    finishAnalysis();

    const body = regionMode === "single_region"
      ? { region, resource_group: group || null }
      : {
          region: selectedRegions[0] || region,
          resource_group: null,
          region_mode: regionMode,
          requested_regions: regionMode === "selected_regions" ? selectedRegions : [],
        };

    try {
      const data = await apiFetch<AnalyzeResponse>("/api/analyze", {
        method: "POST",
        body: JSON.stringify(body),
      });
      activeAnalysisIdRef.current = data.analysis_id;
      storeActiveAnalysisId(data.analysis_id);
      setCurrentAnalysisId(data.analysis_id);
      setRunning(true);

      const token = encodeURIComponent(getToken());
      const socket = new WebSocket(`${websocketUrl(data.websocket_url)}?token=${token}`);
      socketRef.current = socket;

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as ProgressPayload;
        if (payload.message) appendMessage(payload.message);
        if (payload.details) setProgressDetails(payload.details);
        const status = payload.status;
        if (isSuccessfulAnalysisStatus(status) || payload.event === "completed") {
          finishAnalysis(data.analysis_id);
          navigateToReportOnce(data.analysis_id);
        } else if (isFailureAnalysisStatus(status) || payload.event === "failed" || payload.event === "cancelled") {
          if (payload.details?.reason) appendMessage(payload.details.reason);
          finishAnalysis(data.analysis_id);
        }
      };

      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (activeAnalysisIdRef.current === data.analysis_id && !navigatedAnalysisIdsRef.current.has(data.analysis_id)) {
          appendMessage("Connection interrupted; checking analysis status...");
          startPolling(data.analysis_id, 500);
        }
      };

      socket.onerror = () => {
        // The close handler switches to polling.
      };
    } catch (err) {
      finishAnalysis();
      setError(err instanceof Error ? err.message : "Analysis could not start.");
    }
  }
  async function cancelAnalysis() {
    if (!currentAnalysisId) return;
    try {
      const data = await apiFetch<AnalysisLookupResponse>(`/api/analyses/${currentAnalysisId}/cancel`, { method: "POST" });
      if (isTerminalAnalysisStatus(data.analysis.status)) {
        const reason = data.analysis.analysis_result?.reason ?? data.analysis.analysis_result?.error ?? `Analysis ${data.analysis.status}.`;
        appendMessage(reason);
        finishAnalysis(currentAnalysisId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel analysis.");
    }
  }

  async function copyPolicy() {
    await navigator.clipboard.writeText(EXTENDED_POLICY);
    setPolicyCopied(true);
    setTimeout(() => setPolicyCopied(false), 1500);
  }

  function setMode(nextMode: RegionMode) {
    setRegionMode(nextMode);
    setError("");
    if (nextMode === "selected_regions" && selectedRegions.length === 0 && region) {
      setSelectedRegions([region]);
    }
  }

  function toggleSelectedRegion(item: string) {
    setSelectedRegions((current) => current.includes(item) ? current.filter((regionName) => regionName !== item) : [...current, item].sort());
  }

  function selectAllRegions() {
    setSelectedRegions(regions);
  }

  function clearSelectedRegions() {
    setSelectedRegions([]);
  }

  function scanValidationError() {
    if (loading) return "Regions are still loading.";
    if (regionMode === "single_region") {
      if (!region) return "Choose a region before starting the scan.";
      if (!isValidRegion(region)) return "The selected region identifier is invalid.";
      return "";
    }
    if (regionMode === "selected_regions") {
      if (selectedRegions.length === 0) return "Select at least one region.";
      if (selectedRegions.some((item) => !isValidRegion(item) || !regions.includes(item))) return "One or more selected region identifiers are invalid.";
      return "";
    }
    if (regionDiscoveryStatus !== "available" || regions.length === 0) return "All enabled regions cannot be resolved until region discovery succeeds.";
    return "";
  }
  return (
    <div className="space-y-6">
      {/* AWS Connection Panel */}
      {awsStatus && <AwsConnectionPanel status={awsStatus} onViewPolicy={() => setShowPolicyModal(true)} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold text-white">Run Analysis</h1>
              <p className="mt-1 text-sm text-slate-400">AWS account scan</p>
            </div>
            <button
              type="button"
              onClick={() => { loadRegions(); loadAwsStatus(); }}
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

          <div className="space-y-5">
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-slate-300">Scan mode</legend>
              <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Region scan mode">
                {[
                  ["single_region", "Single region"],
                  ["selected_regions", "Selected regions"],
                  ["all_enabled_regions", "All enabled regions"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={regionMode === value}
                    onClick={() => setMode(value as RegionMode)}
                    disabled={running}
                    className={`h-11 rounded-md border px-3 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-cloud-cyan ${
                      regionMode === value ? "border-cloud-cyan bg-cloud-cyan text-slate-950" : "border-cloud-line bg-cloud-ink text-slate-200 hover:border-cloud-cyan"
                    } disabled:cursor-not-allowed disabled:opacity-60`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </fieldset>

            {regionMode === "single_region" && (
              <div className="grid gap-4 md:grid-cols-2">
                <label className="block text-sm font-medium text-slate-300">
                  Region
                  <select
                    className="mt-2 h-11 w-full rounded-md border border-cloud-line bg-cloud-ink px-3 text-white outline-none focus:border-cloud-orange focus:ring-2 focus:ring-cloud-cyan"
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
                      className="mt-2 h-11 w-full rounded-md border border-cloud-line bg-cloud-ink px-3 text-white outline-none focus:border-cloud-orange focus:ring-2 focus:ring-cloud-cyan"
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
            )}

            {regionMode === "selected_regions" && (
              <section className="rounded-lg border border-cloud-line bg-cloud-ink p-4" aria-labelledby="selected-regions-heading">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 id="selected-regions-heading" className="font-semibold text-white">Selected regions</h2>
                    <p className="mt-1 text-sm text-slate-400">{selectedRegions.length} selected</p>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={selectAllRegions} disabled={running || loading || regions.length === 0} className="h-9 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan disabled:opacity-60">Select all</button>
                    <button type="button" onClick={clearSelectedRegions} disabled={running || selectedRegions.length === 0} className="h-9 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan disabled:opacity-60">Clear all</button>
                  </div>
                </div>

                <label className="mt-4 block text-sm font-medium text-slate-300">
                  Search regions
                  <span className="mt-2 flex h-11 items-center gap-2 rounded-md border border-cloud-line bg-cloud-panel px-3 focus-within:border-cloud-orange focus-within:ring-2 focus-within:ring-cloud-cyan">
                    <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
                    <input
                      value={regionFilter}
                      onChange={(event) => setRegionFilter(event.target.value)}
                      disabled={running}
                      className="w-full bg-transparent text-white outline-none placeholder:text-slate-500"
                      placeholder="Filter by identifier"
                      aria-label="Filter regions"
                    />
                  </span>
                </label>

                {loading && <p className="mt-4 text-sm text-slate-400" role="status">Loading regions...</p>}
                {!loading && regions.length === 0 && <RegionDiscoveryState status={regionDiscoveryStatus} error={regionDiscoveryError} onRetry={loadRegions} />}
                {!loading && regions.length > 0 && filteredRegions(regions, regionFilter).length === 0 && (
                  <p className="mt-4 rounded-md border border-cloud-line p-3 text-sm text-slate-400">No regions match your search.</p>
                )}
                {!loading && filteredRegions(regions, regionFilter).length > 0 && (
                  <div className="mt-4 grid max-h-72 gap-2 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3" role="group" aria-label="AWS regions">
                    {filteredRegions(regions, regionFilter).map((item) => (
                      <label key={item} className="flex min-h-11 items-center gap-3 rounded-md border border-cloud-line bg-cloud-panel px-3 py-2 text-sm text-slate-200 focus-within:ring-2 focus-within:ring-cloud-cyan hover:border-cloud-cyan">
                        <input
                          type="checkbox"
                          checked={selectedRegions.includes(item)}
                          onChange={() => toggleSelectedRegion(item)}
                          disabled={running}
                          className="h-4 w-4 accent-cloud-cyan"
                        />
                        <span>{item}</span>
                      </label>
                    ))}
                  </div>
                )}
              </section>
            )}

            {regionMode === "all_enabled_regions" && (
              <section className="rounded-lg border border-cloud-line bg-cloud-ink p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="font-semibold text-white">All enabled regions</h2>
                    <p className="mt-1 text-sm text-slate-400">{regions.length} regions resolved by AWS region discovery</p>
                  </div>
                  <button type="button" onClick={loadRegions} disabled={loading || running} className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan disabled:opacity-60">
                    <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                    Retry
                  </button>
                </div>
                {regionDiscoveryStatus !== "available" ? <RegionDiscoveryState status={regionDiscoveryStatus} error={regionDiscoveryError} onRetry={loadRegions} /> : (
                  <p className="mt-3 text-sm text-slate-300">BudgetBeagle will scan every enabled region returned by AWS in deterministic alphabetical order.</p>
                )}
              </section>
            )}
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={runAnalysis}
              disabled={Boolean(scanValidationError()) || running}
              className="inline-flex h-11 items-center gap-2 rounded-md bg-cloud-orange px-5 font-semibold text-slate-950 hover:bg-orange-300 disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              {running ? "Running" : "Run Analysis"}
            </button>
            {running && currentAnalysisId && (
              <button
                type="button"
                onClick={cancelAnalysis}
                className="inline-flex h-11 items-center gap-2 rounded-md border border-cloud-line px-5 font-semibold text-slate-300 hover:border-cloud-cyan hover:text-white focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
              >
                <X className="h-4 w-4" aria-hidden="true" />
                Cancel analysis
              </button>
            )}
          </div>
        </section>

        <aside>
          <h2 className="mb-3 text-sm font-semibold uppercase text-slate-400">Progress</h2>
          <ProgressTracker messages={messages} details={progressDetails} />
        </aside>
      </div>

      {/* IAM Policy Modal */}
      {showPolicyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowPolicyModal(false)}>
          <div className="relative mx-4 max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-cloud-line bg-cloud-panel p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setShowPolicyModal(false)} className="absolute right-4 top-4 rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white">
              <X className="h-5 w-5" />
            </button>
            <h2 className="text-xl font-semibold text-white">Required IAM Policy</h2>
            <p className="mt-2 text-sm text-slate-400">
              Attach this policy to your IAM user or role. It grants read-only access for resource scanning and optional billing data.
            </p>

            <div className="mt-4 space-y-4">
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-300">Extended Read-Only Policy (Recommended)</h3>
                  <button type="button" onClick={copyPolicy} className="inline-flex items-center gap-1.5 rounded-md border border-cloud-line px-2.5 py-1.5 text-xs text-slate-300 hover:border-cloud-cyan hover:text-white">
                    {policyCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                    {policyCopied ? "Copied" : "Copy"}
                  </button>
                </div>
                <pre className="mt-2 overflow-x-auto rounded-lg border border-cloud-line bg-cloud-ink p-4 text-xs text-slate-200">
                  <code>{EXTENDED_POLICY}</code>
                </pre>
              </div>

              <div className="rounded-lg border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-100">
                <p className="font-medium text-white">Important notes</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-amber-100/90">
                  <li><code className="text-amber-200">s3:GetLifecycleConfiguration</code> - verifies whether S3 buckets have lifecycle policies</li>
                  <li><code className="text-amber-200">ce:GetCostAndUsage</code> - retrieves Cost Explorer billing data (optional)</li>
                  <li>Missing optional permissions produce warnings, not failed scans</li>
                  <li>BudgetBeagle is read-only and never modifies AWS resources</li>
                  <li>Attach this policy manually - BudgetBeagle does not modify IAM</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function isValidRegion(value: string) {
  return REGION_PATTERN.test(value);
}

function filteredRegions(regions: string[], filter: string) {
  const needle = filter.trim().toLowerCase();
  if (!needle) return regions;
  return regions.filter((item) => item.toLowerCase().includes(needle));
}

function RegionDiscoveryState({ status, error, onRetry }: { status?: string; error?: RegionsResponse["error"] | null; onRetry: () => void }) {
  const permission = error?.permission;
  const title = status === "permission_denied"
    ? "Region discovery permission denied"
    : status === "empty"
      ? "No enabled regions returned"
      : "Region discovery unavailable";
  const message = error?.message ?? (status === "empty" ? "AWS returned no enabled regions for this account." : "BudgetBeagle could not resolve enabled regions.");
  return (
    <div className="mt-4 rounded-lg border border-amber-400/40 bg-amber-500/10 p-4 text-sm text-amber-50" role="alert">
      <p className="font-semibold text-white">{title}</p>
      <p className="mt-1 leading-6">{message}</p>
      {permission && <p className="mt-1 text-amber-100/80">Permission: <code className="text-amber-200">{permission}</code></p>}
      <button type="button" onClick={onRetry} className="mt-3 inline-flex h-9 items-center gap-2 rounded-md border border-amber-400/30 px-3 text-sm text-amber-100 hover:border-amber-300 focus:outline-none focus:ring-2 focus:ring-cloud-cyan">
        <RefreshCcw className="h-4 w-4" aria-hidden="true" />
        Retry
      </button>
    </div>
  );
}
function AwsConnectionPanel({ status, onViewPolicy }: { status: AwsStatus; onViewPolicy: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const isLimited = status.connection_status === "connected_with_limited_permissions";
  const isConnected = status.connected;
  const missingOptional = status.optional_permissions.missing;

  const borderColor = !isConnected
    ? "border-rose-500/40"
    : isLimited
      ? "border-amber-400/40"
      : "border-emerald-400/40";
  const bgColor = !isConnected
    ? "bg-rose-500/10"
    : isLimited
      ? "bg-amber-500/10"
      : "bg-emerald-500/10";

  return (
    <section className={`rounded-lg border ${borderColor} ${bgColor} p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {isConnected ? (
            isLimited ? (
              <ShieldAlert className="h-5 w-5 text-amber-400" />
            ) : (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            )
          ) : (
            <Shield className="h-5 w-5 text-rose-400" />
          )}
          <div>
            <p className="font-semibold text-white">
              {!isConnected ? "AWS not connected" : isLimited ? "AWS connected" : "AWS connected"}
            </p>
            <p className="mt-0.5 text-sm text-slate-300">
              {isConnected && (
                <>
                  Account: {status.account_id_masked ?? "Unknown"}  -  Region: {status.default_region}
                  {isLimited ? "  -  Permissions: Limited" : "  -  Permissions: Full"}
                </>
              )}
              {!isConnected && "Configure AWS credentials to start scanning."}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onViewPolicy}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan hover:text-white"
          >
            <Shield className="h-4 w-4" />
            View required IAM policy
          </button>
          {isLimited && (
            <button type="button" onClick={() => setExpanded(!expanded)} className="inline-flex h-9 items-center gap-1 rounded-md px-2 text-sm text-slate-300 hover:text-white">
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
          )}
        </div>
      </div>

      {isLimited && !expanded && (
        <p className="mt-3 text-sm text-amber-100/90">
          BudgetBeagle can scan your resources, but some report data is unavailable.
        </p>
      )}

      {isLimited && expanded && (
        <div className="mt-4 space-y-2">
          <p className="text-sm font-medium text-white">Missing optional permissions:</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-amber-100/90">
            {missingOptional.map((perm) => (
              <li key={perm}><code className="text-amber-200">{perm}</code></li>
            ))}
          </ul>
          <p className="mt-2 text-sm text-amber-100/80">
            Add these permissions to your IAM policy and scan again to get full report data.
          </p>
        </div>
      )}
    </section>
  );
}