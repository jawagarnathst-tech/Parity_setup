import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Circle,
  Cpu,
  Download,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  Loader2,
  Moon,
  RefreshCw,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn, downloadJSON } from "@/lib/utils";
import { getDownloadUrl, uploadFile, getStatus } from "@/lib/api/extraction";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "SBC — Automated Health Plan Extraction" },
      {
        name: "description",
        content:
          "AI-powered pipeline that ingests, parses, and structures Summary of Benefits & Coverage documents into clean, exportable data.",
      },
      { property: "og:title", content: "SBC — Automated Health Plan Extraction" },
      {
        property: "og:description",
        content:
          "Enterprise document processing for health plans. OCR, semantic parsing, and template injection in one workflow.",
      },
    ],
  }),
  component: Index,
});

type FileKind = "pdf" | "word" | "image";

interface UploadedFile {
  id: string;
  file: File;
  name: string;
  size: number;
  kind: FileKind;
}

interface ExtractionResult {
  taskId: string;
  fileName: string;
  carrier: string;
  planName: string;
  confidence: number;
  status: "success" | "failed";
  error?: string;
  planData?: any;
  jsonOutput?: any;
}

const STAGES = [
  { key: "ingestion", label: "Ingestion", hint: "Validating & queuing files" },
  { key: "ocr", label: "OCR Processing", hint: "Reading text from documents" },
  { key: "parse", label: "AI Semantic Parsing", hint: "Identifying plan structure" },
  { key: "inject", label: "Template Injection", hint: "Mapping to SBC schema" },
] as const;

const SAMPLE_CARRIERS = ["Aetna", "Cigna", "UnitedHealthcare", "Anthem BCBS", "Kaiser", "Humana"];
const SAMPLE_PLANS = [
  "Gold PPO 1000",
  "Silver HMO 2500",
  "Bronze HSA 5000",
  "Platinum EPO 500",
  "HDHP Choice 3000",
];

function detectKind(name: string): FileKind {
  const n = name.toLowerCase();
  if (n.endsWith(".pdf")) return "pdf";
  if (n.endsWith(".doc") || n.endsWith(".docx")) return "word";
  return "image";
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function Index() {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [activeStage, setActiveStage] = useState(-1);
  const [results, setResults] = useState<ExtractionResult[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((list: FileList | File[]) => {
    const incoming = Array.from(list).map((f) => ({
      id: `${f.name}-${f.size}-${Math.random().toString(36).slice(2, 7)}`,
      file: f,
      name: f.name,
      size: f.size,
      kind: detectKind(f.name),
    }));
    
    // Clear previous results for re-uploaded files so they can be processed again
    setResults((prev) => prev.filter((r) => !incoming.some((inc) => inc.name === r.fileName)));
    
    // Add to files queue, replacing any existing file with the same name
    setFiles((prev) => {
      const prevFiltered = prev.filter((p) => !incoming.some((inc) => inc.name === p.name));
      return [...prevFiltered, ...incoming];
    });
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const removeFile = (id: string) => setFiles((p) => p.filter((f) => f.id !== id));

  const reprocessFile = async (fileName: string) => {
    const fileItem = files.find(f => f.name === fileName);
    if (!fileItem || processing) return;
    
    setProcessing(true);
    setActiveStage(0);
    
    setResults(prev => prev.map(r => r.fileName === fileName ? {
      ...r,
      carrier: "Re-processing...",
      planName: "Uploading...",
      confidence: 0,
      status: "success",
    } : r));

    try {
      setActiveStage(0);
      const response = await uploadFile(fileItem.file);
      
      setActiveStage(1); // OCR
      await new Promise((r) => setTimeout(r, 600));
      
      setActiveStage(2); // AI Semantic Parsing
      await new Promise((r) => setTimeout(r, 600));
      
      setActiveStage(3); // Template Injection
      await new Promise((r) => setTimeout(r, 600));

      const statusResponse = await getStatus(response.task_id);
      const resData = statusResponse.results || {};
      
      setResults(prev => prev.map(r => r.fileName === fileName ? {
        taskId: response.task_id,
        fileName: response.fileName,
        carrier: resData.carrier || "Unknown",
        planName: resData.planName || "Unknown",
        confidence: resData.confidence || 0,
        status: "success",
        jsonOutput: resData.planData || resData,
      } : r));
      setActiveStage(4);
    } catch (e: any) {
      console.error("Re-extraction error:", e);
      setResults(prev => prev.map(r => r.fileName === fileName ? {
        taskId: `fail-${Math.random()}`,
        fileName: fileName,
        carrier: "Failed",
        planName: e.message || "Network Error / Server Restarted",
        confidence: 0,
        status: "failed",
        error: e.message || "API request failed",
      } : r));
      setActiveStage(-1);
    }
    
    setProcessing(false);
  };

  const runPipeline = async () => {
    if (!files.length || processing) return;
    setProcessing(true);
    setActiveStage(0);

    const newResults = [...results];
    let hasError = false;
    
    for (const fileItem of files) {
      const isAlreadyProcessed = results.some(r => r.fileName === fileItem.name && r.status === "success");
      if (isAlreadyProcessed) {
        continue;
      }

      const filtered = newResults.filter(r => r.fileName !== fileItem.name);
      
      try {
        setActiveStage(0);
        const response = await uploadFile(fileItem.file);
        
        setActiveStage(1); // OCR
        await new Promise((r) => setTimeout(r, 600));
        
        setActiveStage(2); // AI Semantic Parsing
        await new Promise((r) => setTimeout(r, 600));
        
        setActiveStage(3); // Template Injection
        await new Promise((r) => setTimeout(r, 600));

        const statusResponse = await getStatus(response.task_id);
        const resData = statusResponse.results || {};
        
        filtered.push({
          taskId: response.task_id,
          fileName: response.fileName,
          carrier: resData.carrier || "Unknown",
          planName: resData.planName || "Unknown",
          confidence: resData.confidence || 0,
          status: "success",
          planData: resData.planData || resData,
          jsonOutput: resData.planData || resData,
        });
      } catch (e: any) {
        console.error("Extraction error:", e);
        hasError = true;
        filtered.push({
          taskId: `fail-${Math.random()}`,
          fileName: fileItem.name,
          carrier: "Failed",
          planName: e.message || "Network Error / Server Restarted",
          confidence: 0,
          status: "failed",
          error: e.message || "API request failed",
        });
      }
      
      newResults.length = 0;
      newResults.push(...filtered);
    }
    
    setResults(newResults);
    setActiveStage(hasError ? -1 : 4);
    setProcessing(false);
  };

  useEffect(() => {
    // Pipeline logic is now handled in runPipeline
  }, [processing, activeStage, files]);

  const avgConfidence = useMemo(
    () => {
      const successResults = results.filter(r => r.status === "success");
      return successResults.length 
        ? Math.round(successResults.reduce((a, r) => a + r.confidence, 0) / successResults.length) 
        : 0;
    },
    [results],
  );

  const batchDone = results.length > 0 && !processing && results.some(r => r.status === "success");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header />

      <main className="mx-auto max-w-[1400px] px-6 py-8 lg:px-10">

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Top Row: Extraction Hub */}
          <section className="lg:col-span-3">
            <Card>
              <CardHeader
                title="Extraction Hub"
                subtitle="Drop SBC documents to begin the automated pipeline."
                icon={<UploadCloud className="h-4 w-4" />}
              />

              <div className="p-6">
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={onDrop}
                  onClick={() => inputRef.current?.click()}
                  className={cn(
                    "group relative flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed bg-accent/30 px-6 py-14 text-center transition-all",
                    isDragging
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50 hover:bg-accent/60",
                  )}
                >
                  <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <Upload className="h-6 w-6" />
                  </div>
                  <h3 className="text-[18px] font-semibold text-foreground">Drag & Drop Files</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    or click to browse · PDF, Word & Images · max 50MB each
                  </p>
                  <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                    <Button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        inputRef.current?.click();
                      }}
                      className="rounded-lg bg-primary text-primary-foreground shadow-sm hover:bg-primary/90"
                    >
                      <Upload className="mr-2 h-4 w-4" /> Select Files
                    </Button>
                  </div>
                  <input
                    ref={inputRef}
                    type="file"
                    hidden
                    multiple
                    accept=".pdf,.doc,.docx,image/*"
                    onChange={(e) => e.target.files && addFiles(e.target.files)}
                  />
                </div>

                {/* File previews */}
                {files.length > 0 && (
                  <div className="mt-6">
                    <div className="mb-3 flex items-center justify-between">
                      <h4 className="text-sm font-semibold text-foreground">
                        Queued documents
                        <span className="ml-1 font-normal text-muted-foreground">({files.length})</span>
                        <span className="ml-2 text-sm text-muted-foreground">Completed: {results.filter((r) => r.status === "success").length}</span>
                      </h4>
                      <div className="flex items-center gap-4">
                        <Button
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            runPipeline();
                          }}
                          disabled={!files.length || processing}
                          className="h-8 bg-primary text-primary-foreground shadow-sm hover:bg-primary/90"
                        >
                          {processing ? (
                            <><Loader2 className="mr-2 h-3 w-3 animate-spin" /> Processing…</>
                          ) : (
                            <><Sparkles className="mr-2 h-3 w-3" /> Process File</>
                          )}
                        </Button>
                        <button
                          onClick={() => setFiles([])}
                          className="text-xs font-medium text-muted-foreground hover:text-destructive"
                        >
                          Clear all
                        </button>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {files.map((f) => {
                        const result = results.find((r) => r.fileName === f.name);
                        return (
                          <FilePreviewCard
                            key={f.id}
                            file={f}
                            status={result?.status}
                            isProcessing={processing}
                            onRemove={() => removeFile(f.id)}
                          />
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </section>

          {/* Bottom Row Left: Results */}
          <section className="lg:col-span-2">
            <Card>
              <CardHeader
                title="Extraction Results"
                subtitle="Structured plan data ready for export."
                icon={<FileSpreadsheet className="h-4 w-4" />}
                action={<div className="flex items-center gap-2"><span className="text-sm text-muted-foreground">Completed: {results.filter((r) => r.status === "success").length}</span></div>}
              />
              <div className="p-0">
                {results.length === 0 ? (
                  <EmptyState />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="border-y border-border bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <tr>
                          <th className="px-6 py-3 font-semibold">File</th>
                          <th className="px-6 py-3 font-semibold">Carrier</th>
                          <th className="px-6 py-3 font-semibold">Plan</th>
                          <th className="px-6 py-3 font-semibold">Confidence</th>
                          <th className="px-6 py-3 text-right font-semibold">Export</th>
                        </tr>
                      </thead>
                      <tbody>
                        {results.map((r) => (
                          <tr key={r.taskId} className="border-b border-border last:border-0 hover:bg-accent/40">
                            <td className="px-6 py-4">
                              <div className="flex items-center gap-3">
                                <FileText className="h-4 w-4 text-muted-foreground" />
                                <span className="font-medium text-foreground">{r.fileName}</span>
                              </div>
                            </td>
                            <td className="px-6 py-4">
                              <span className={cn(
                                "font-medium",
                                r.status === "failed" ? "text-destructive" : "text-foreground"
                              )}>
                                {r.carrier}
                              </span>
                            </td>
                            <td className="px-6 py-4">
                              <span className={cn(
                                r.status === "failed" ? "text-destructive/80 font-mono text-xs" : "text-muted-foreground"
                              )}>
                                {r.planName}
                              </span>
                            </td>
                            <td className="px-6 py-4">
                              {r.status === "failed" ? (
                                <span className="text-xs text-destructive">N/A</span>
                              ) : (
                                <ConfidenceBadge value={r.confidence} />
                              )}
                            </td>
                            <td className="px-6 py-4">
                              <div className="flex items-center justify-end gap-2">
                                <button
                                  onClick={() => reprocessFile(r.fileName)}
                                  disabled={processing}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary disabled:opacity-40"
                                  title="Re-process Document"
                                  aria-label="Re-process"
                                >
                                  <RefreshCw className={cn(
                                    "h-4 w-4",
                                    processing && r.carrier.includes("Re-processing") && "animate-spin"
                                  )} />
                                </button>
                                
                                {r.status === "failed" ? (
                                  <span className="text-xs text-muted-foreground">Unavailable</span>
                                ) : (
                                  <>
                                    <button
                                      onClick={() => {
                                        downloadJSON(r.jsonOutput, r.fileName.replace(/\.[^/.]+$/, "") + ".json");
                                      }}
                                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                                      title="Download JSON"
                                      aria-label="Download JSON"
                                    >
                                      <FileText className="h-4 w-4" />
                                    </button>
                                    <button
                                      onClick={() => {
                                        window.open(getDownloadUrl(r.taskId), "_blank");
                                      }}
                                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                                      title="Download Excel"
                                      aria-label="Download Excel"
                                    >
                                      <Download className="h-4 w-4" />
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </Card>
          </section>

          {/* Bottom Row Right: Progress sidebar */}
          <aside className="space-y-6 lg:col-span-1">
            <Card className="h-full">
              <CardHeader
                title="Live Progress"
                subtitle="Pipeline stages"
                icon={<Activity className="h-4 w-4" />}
              />
              <div className="p-6">
                <Stepper activeStage={activeStage} done={batchDone} />
              </div>
            </Card>

          </aside>
        </div>
      </main>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto flex max-w-[1400px] flex-col items-center justify-between gap-2 px-6 py-5 text-xs text-muted-foreground md:flex-row lg:px-10">
          <span>© {new Date().getFullYear()} SBC · Enterprise Health Plan Extraction</span>
          <span>Built for compliance · SOC 2 · HIPAA-aware workflow</span>
        </div>
      </footer>
    </div>
  );
}

/* ---------- Header ---------- */
function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-card/80 backdrop-blur">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-4 lg:px-10">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-navy text-navy-foreground shadow-sm">
            <FileText className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-[18px] font-semibold leading-tight tracking-tight text-foreground">
              SBC
            </h1>
            <p className="text-xs text-muted-foreground">Automated Health Plan Extraction</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Button variant="outline" className="rounded-lg border-border bg-card hover:bg-accent">
            <FileText className="mr-2 h-4 w-4" /> Docs
          </Button>
        </div>
      </div>
    </header>
  );
}

function ThemeToggle() {
  const [isDark, setIsDark] = useState(() => {
    if (typeof document !== "undefined") {
      return document.documentElement.classList.contains("dark");
    }
    return false;
  });

  useEffect(() => {
    if (!document.documentElement.classList.contains("dark") && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.classList.add("dark");
      setIsDark(true);
    }
  }, []);

  const toggle = () => {
    const next = !isDark;
    setIsDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  };

  return (
    <Button
      variant="outline"
      onClick={toggle}
      className="flex h-10 w-10 items-center justify-center rounded-lg border-border bg-card p-0 hover:bg-accent"
      title="Toggle Dark Mode"
    >
      {isDark ? <Sun className="h-4 w-4 text-muted-foreground" /> : <Moon className="h-4 w-4 text-muted-foreground" />}
    </Button>
  );
}

/* ---------- Primitives ---------- */
function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

function CardHeader({
  title,
  subtitle,
  icon,
  action,
}: {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
      <div className="flex items-start gap-3">
        {icon && (
          <div className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            {icon}
          </div>
        )}
        <div>
          <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "success" | "warning";
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1.5 text-2xl font-semibold tracking-tight",
          tone === "success" && "text-success",
          tone === "warning" && "text-warning",
          tone === "default" && "text-foreground",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function FilePreviewCard({
  file,
  onRemove,
  status,
  isProcessing,
}: {
  file: UploadedFile;
  onRemove: () => void;
  status?: "success" | "failed";
  isProcessing?: boolean;
}) {
  const meta = {
    pdf: { label: "PDF", icon: FileText, color: "text-destructive bg-destructive/10" },
    word: { label: "DOCX", icon: FileText, color: "text-primary bg-primary/10" },
    image: { label: "IMG", icon: ImageIcon, color: "text-success bg-success/10" },
  }[file.kind];
  const Icon = meta.icon;
  return (
    <div className="group flex items-center gap-3 rounded-lg border border-border bg-card p-3 shadow-sm transition-colors hover:border-primary/40">
      <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-md", meta.color)}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
        <div className="flex items-center gap-2 mt-0.5">
          <p className="text-xs text-muted-foreground">
            {meta.label} · {formatSize(file.size)}
          </p>
          {status === "success" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-semibold text-success border border-success/20">
              <CheckCircle2 className="h-2.5 w-2.5" /> Completed
            </span>
          )}
          {status === "failed" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive border border-destructive/20">
              <X className="h-2.5 w-2.5" /> Failed
            </span>
          )}
          {!status && isProcessing && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary border border-primary/20">
              <Loader2 className="h-2.5 w-2.5 animate-spin" /> Processing…
            </span>
          )}
        </div>
      </div>
      <button
        onClick={onRemove}
        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
        aria-label="Remove"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function Stepper({ activeStage, done }: { activeStage: number; done: boolean }) {
  return (
    <ol className="relative space-y-5">
      {STAGES.map((s, i) => {
        const isDone = done || i < activeStage;
        const isActive = !done && i === activeStage;
        return (
          <li key={s.key} className="relative flex gap-3">
            {i < STAGES.length - 1 && (
              <span
                className={cn(
                  "absolute left-[11px] top-7 h-[calc(100%-4px)] w-px",
                  isDone ? "bg-primary" : "bg-border",
                )}
              />
            )}
            <div
              className={cn(
                "relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 bg-card transition-colors",
                isDone && "border-primary bg-primary text-primary-foreground",
                isActive && "border-primary",
                !isDone && !isActive && "border-border",
              )}
            >
              {isDone ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : isActive ? (
                <Loader2 className="h-3 w-3 animate-spin text-primary" />
              ) : (
                <Circle className="h-2 w-2 text-muted-foreground" />
              )}
            </div>
            <div className="pb-1">
              <p
                className={cn(
                  "text-sm font-medium",
                  isDone || isActive ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {s.label}
              </p>
              <p className="text-xs text-muted-foreground">{s.hint}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  const tone =
    value >= 90
      ? "bg-success/10 text-success border-success/20"
      : value >= 75
        ? "bg-warning/15 text-warning-foreground border-warning/30"
        : "bg-destructive/10 text-destructive border-destructive/20";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold tabular-nums",
        tone,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {value}%
    </span>
  );
}

function ConfidenceRing({ value }: { value: number }) {
  const size = 140;
  const stroke = 12;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c - (value / 100) * c;
  const color = value >= 90 ? "var(--success)" : value >= 75 ? "var(--warning)" : value > 0 ? "var(--destructive)" : "var(--border)";
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--border)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={value === 0 ? c : offset}
          fill="none"
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-semibold tabular-nums text-foreground">{value}%</span>
        <span className="text-xs text-muted-foreground">Avg. health</span>
      </div>
    </div>
  );
}

function MiniBar({
  label,
  pct,
  total,
  tone,
}: {
  label: string;
  pct: number;
  total: number;
  tone: "success" | "warning" | "destructive";
}) {
  const ratio = total ? (pct / total) * 100 : 0;
  const bg =
    tone === "success" ? "bg-success" : tone === "warning" ? "bg-warning" : "bg-destructive";
  return (
    <div>
      <div className="mb-1.5 h-16 w-full overflow-hidden rounded-md bg-muted">
        <div
          className={cn("mt-auto h-full origin-bottom transition-transform duration-500", bg)}
          style={{ transform: `scaleY(${ratio / 100 || 0.02})`, transformOrigin: "bottom" }}
        />
      </div>
      <p className="font-semibold text-foreground">{pct}</p>
      <p className="text-muted-foreground">{label}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <FileText className="h-5 w-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium text-foreground">No extractions yet</p>
      <p className="mt-1 max-w-sm text-xs text-muted-foreground">
        Upload SBC documents and run the batch to populate structured results here.
      </p>
    </div>
  );
}

// Keep unused import tree-shakeable warnings away — Trash2 reserved for future bulk actions.
void Trash2;
