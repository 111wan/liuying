import React, { useEffect, useState, useCallback, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDown,
  ArrowUpRight,
  Check,
  ChevronRight,
  Clipboard,
  Download,
  Film,
  Link2,
  LoaderCircle,
  RefreshCw,
  ScanLine,
  X,
  AlertCircle,
  Clock,
  ArrowLeft,
} from "lucide-react";
import {
  api,
  bootstrap,
  post,
  terminal,
  names,
  stages,
  bytes,
  duration,
  type Format,
  type Media,
  type Job,
  type Platform,
  type SessionInfo,
} from "./api";
import "./styles.css";

type View = "download" | "tasks" | "platforms";
const expired = (job: Job | null) =>
  !!job?.result?.expires_at && job.result.expires_at * 1000 < Date.now();
function useLiveJob(identifier: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  useEffect(() => {
    setJob(null);
    setConnectionError(false);
    if (!identifier) return;
    let alive = true,
      source: EventSource | null = null,
      timer: ReturnType<typeof setInterval> | undefined;
    const accept = (value: Job) => {
      if (!alive) return;
      setJob(value);
      setConnectionError(false);
      if (terminal(value)) {
        source?.close();
        clearInterval(timer);
      }
    };
    const poll = () =>
      api<Job>("/jobs/" + identifier)
        .then(accept)
        .catch(() => {
          if (alive) setConnectionError(true);
        });
    source = new EventSource("/api/v1/jobs/" + identifier + "/events");
    source.addEventListener("snapshot", (event) => {
      try {
        accept(JSON.parse((event as MessageEvent).data));
      } catch {
        setConnectionError(true);
      }
    });
    source.onerror = () => {
      if (alive) setConnectionError(true);
    };
    timer = setInterval(poll, 5000);
    void poll();
    return () => {
      alive = false;
      source?.close();
      clearInterval(timer);
    };
  }, [identifier]);
  return { job, connectionError };
}

function App() {
  const [view, setView] = useState<View>(
    location.hash === "#tasks"
      ? "tasks"
      : location.hash === "#platforms"
        ? "platforms"
        : "download",
  );
  const [session, setSession] = useState<SessionInfo | null>(null),
    [startupError, setStartupError] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>([]),
    [jobs, setJobs] = useState<Job[]>([]);
  const [text, setText] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false),
    [busy, setBusy] = useState(false),
    [saving, setSaving] = useState(false);
  const [resolveId, setResolveId] = useState<string | null>(null),
    [downloadId, setDownloadId] = useState<string | null>(null);
  const [media, setMedia] = useState<Media | null>(null),
    [selected, setSelected] = useState(""),
    [filter, setFilter] = useState("all");
  const { job: resolveJob, connectionError: resolveConnection } =
    useLiveJob(resolveId);
  const { job: downloadJob, connectionError: downloadConnection } =
    useLiveJob(downloadId);
  const input = useRef<HTMLTextAreaElement>(null);
  const format = media?.formats.find((f) => f.id === selected);
  const resolving = submitting || (!!resolveId && !terminal(resolveJob));
  const processing = busy || (!!downloadId && !terminal(downloadJob));
  const sourceToReparse =
    downloadJob?.error?.code === "SOURCE_CHANGED" ? resolveJob : null;
  const ready =
    downloadJob?.status === "ready" &&
    !!downloadJob.result?.artifact_id &&
    !expired(downloadJob);
  const activeCount = jobs.filter((j) => !terminal(j)).length;
  const changeView = (next: View) => {
    setView(next);
    location.hash = next === "download" ? "" : next;
    setNotice("");
  };
  const refresh = useCallback(
    () =>
      api<Job[]>("/jobs")
        .then(setJobs)
        .catch(() => {}),
    [],
  );
  const loadMedia = useCallback(async (id: string) => {
    const value = await api<Media>("/media/" + id);
    setMedia(value);
    setSelected(value.formats[0]?.id || "");
    return value;
  }, []);

  useEffect(() => {
    let alive = true;
    bootstrap()
      .then(async (info) => {
        if (!alive) return;
        setSession(info);
        const [p, list] = await Promise.all([
          api<Platform[]>("/platforms"),
          api<Job[]>("/jobs"),
        ]);
        if (!alive) return;
        setPlatforms(p);
        setJobs(list);
        const inProgress = list.find(
          (j) => j.kind === "resolve" && !terminal(j),
        );
        if (inProgress) setResolveId(inProgress.id);
      })
      .catch((e) => {
        if (alive) setStartupError(e.message);
      });
    const hash = () =>
      setView(
        location.hash === "#tasks"
          ? "tasks"
          : location.hash === "#platforms"
            ? "platforms"
            : "download",
      );
    window.addEventListener("hashchange", hash);
    return () => {
      alive = false;
      window.removeEventListener("hashchange", hash);
    };
  }, []);
  useEffect(() => {
    if (!session) return;
    void refresh();
    const timer = setInterval(refresh, 3500);
    return () => clearInterval(timer);
  }, [session, refresh]);
  useEffect(() => {
    let alive = true;
    if (resolveJob?.status === "ready" && resolveJob.result?.media_id) {
      api<Media>("/media/" + resolveJob.result.media_id)
        .then((value) => {
          if (alive) {
            setMedia(value);
            setSelected(value.formats[0]?.id || "");
          }
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    }
    return () => {
      alive = false;
    };
  }, [resolveJob?.id, resolveJob?.status]);
  useEffect(() => {
    if (resolveJob) void refresh();
  }, [resolveJob?.status, refresh]);
  useEffect(() => {
    if (downloadJob) void refresh();
  }, [downloadJob?.status, refresh]);

  async function parse(value = text) {
    if (!session || resolving || processing) return;
    if (!value.trim()) {
      setError("请先粘贴一条视频分享链接。");
      input.current?.focus();
      return;
    }
    setSubmitting(true);
    setError("");
    setNotice("");
    setMedia(null);
    setDownloadId(null);
    setResolveId(null);
    try {
      const job = await post<Job>("/resolutions", { text: value });
      setResolveId(job.id);
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }
  async function paste() {
    try {
      setText(await navigator.clipboard.readText());
      setError("");
      input.current?.focus();
    } catch {
      setNotice("浏览器未允许读取剪贴板，请在输入框中手动粘贴。");
      input.current?.focus();
    }
  }
  async function sample() {
    if (!session) return;
    setText(session.sample_url);
    await parse(session.sample_url);
  }
  async function prepare() {
    if (!media || !format || busy || processing) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const job = await post<Job>("/downloads", {
        media_id: media.id,
        format_id: format.id,
      });
      setDownloadId(job.id);
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(job: Job) {
    if (!job.result?.artifact_id) return;
    setSaving(true);
    setError("");
    try {
      const { url } = await post<{ url: string }>(
        "/artifacts/" + job.result.artifact_id + "/download-ticket",
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = job.result.filename || "video";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setNotice("已发起下载，请在浏览器的下载列表中查看文件。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function cancel(job: Job) {
    try {
      await post("/jobs/" + job.id + "/cancel");
      setNotice("已请求取消，正在停止处理。");
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function retry(job: Job) {
    setError("");
    setNotice("");
    try {
      const next = await post<Job>("/jobs/" + job.id + "/retry");
      if (next.kind === "resolve") {
        setResolveId(next.id);
        setDownloadId(null);
        setMedia(null);
        changeView("download");
      } else {
        setDownloadId(next.id);
      }
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function inspect(job: Job) {
    setError("");
    if (job.kind === "resolve") {
      setResolveId(job.id);
      setDownloadId(null);
      if (job.result?.media_id)
        try {
          await loadMedia(job.result.media_id);
        } catch (e) {
          setError((e as Error).message);
        }
      changeView("download");
    } else if (!terminal(job)) {
      setNotice("任务正在后台处理，可以随时取消。");
    }
  }
  const taskItems = jobs.filter(
    (j) =>
      filter === "all" ||
      (filter === "active" && !terminal(j)) ||
      (filter === "ready" &&
        j.kind === "download" &&
        j.status === "ready" &&
        !expired(j)) ||
      (filter === "failed" && ["failed", "cancelled"].includes(j.status)),
  );
  const watermarkText =
    format?.watermark === "absent"
      ? "平台无水印源"
      : format?.watermark === "present"
        ? "带水印版本"
        : "水印情况未知";

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="brand"
          onClick={() => changeView("download")}
          aria-label="留影首页"
        >
          <ScanLine size={22} strokeWidth={1.6} />
          <span>留影</span>
        </button>
        <nav aria-label="主导航">
          <button
            className={view === "download" ? "current" : ""}
            onClick={() => changeView("download")}
          >
            下载
          </button>
          <button
            className={view === "tasks" ? "current" : ""}
            onClick={() => changeView("tasks")}
          >
            任务
            {activeCount > 0 && (
              <span className="nav-count">{activeCount}</span>
            )}
          </button>
          <button
            className={view === "platforms" ? "current" : ""}
            onClick={() => changeView("platforms")}
          >
            支持平台
          </button>
        </nav>
        <span className="local-indicator">
          <span />
          本地运行
        </span>
      </header>
      {startupError && (
        <div className="startup-error" role="alert">
          <AlertCircle size={18} />
          <span>{startupError}</span>
          <button onClick={() => location.reload()}>重新连接</button>
        </div>
      )}
      <main>
        {view === "download" && (
          <>
            <section
              className={"hero" + (resolveId || media ? " hero-compact" : "")}
            >
              <p className="eyebrow">留影</p>
              <h1>
                好视频。
                <br />
                <span>值得留住。</span>
              </h1>
              <p className="hero-copy">
                一段分享链接，留住喜欢的片刻。
                <br />
                优先获取无水印版本，保留源画质。
              </p>
              <form
                className="link-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void parse();
                }}
              >
                <div className="field-top">
                  <label htmlFor="share-link">视频分享链接</label>
                  <span>⌘ / Ctrl + Enter</span>
                </div>
                <textarea
                  ref={input}
                  id="share-link"
                  rows={2}
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    setError("");
                  }}
                  placeholder="粘贴链接，或直接粘贴整段分享文案"
                  maxLength={8000}
                  disabled={processing}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      void parse();
                    }
                  }}
                />
                <div className="form-actions">
                  <button
                    type="button"
                    className="text-button"
                    onClick={paste}
                    disabled={resolving || processing}
                  >
                    <Clipboard size={16} />
                    粘贴链接
                  </button>
                  <button
                    className="primary"
                    disabled={!session || resolving || processing}
                  >
                    {resolving ? (
                      <LoaderCircle size={17} className="spin" />
                    ) : (
                      <Link2 size={17} />
                    )}{" "}
                    {resolving ? "正在解析" : "解析链接"}
                  </button>
                </div>
              </form>
              <div className="under-input">
                <span>抖音 · B站 · YouTube · 快手 · 小红书 · 更多来源</span>
                <button
                  className="text-button"
                  onClick={sample}
                  disabled={!session || resolving || processing}
                >
                  试用公开样片
                  <ChevronRight size={14} />
                </button>
              </div>
            </section>
            {error && (
              <div className="inline-alert" role="alert">
                <AlertCircle size={18} />
                <span>{error}</span>
                <button aria-label="关闭提示" onClick={() => setError("")}>
                  <X size={16} />
                </button>
              </div>
            )}
            {resolving && (
              <section className="result-section">
                <div className="content-width">
                  <div className="loading-surface" aria-live="polite">
                    <LoaderCircle className="spin" size={26} />
                    <h2>{stages[resolveJob?.stage || "resolving"]}</h2>
                    <p>正在向来源平台获取真实的视频信息。</p>
                    {resolveJob && (
                      <button
                        className="text-button"
                        onClick={() => cancel(resolveJob)}
                      >
                        取消解析
                      </button>
                    )}
                    {resolveConnection && (
                      <small>连接暂时中断，正在重新获取任务状态…</small>
                    )}
                  </div>
                </div>
              </section>
            )}
            {!resolving && !media && resolveJob?.status === "failed" && (
              <section className="result-section">
                <div className="content-width">
                  <div className="empty-surface">
                    <AlertCircle size={28} />
                    <h2>这次，暂时没能获取。</h2>
                    <p>{resolveJob.error?.message}</p>
                    <div className="button-row">
                      <button
                        className="primary"
                        onClick={() => retry(resolveJob)}
                      >
                        <RefreshCw size={16} />
                        重新解析
                      </button>
                      <button
                        className="text-button"
                        onClick={() => changeView("platforms")}
                      >
                        查看支持范围
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              </section>
            )}
            {media && (
              <section className="result-section" aria-label="视频解析结果">
                <div className="content-width">
                  <div className="section-heading">
                    <h2>你的片刻。</h2>
                    <span>已获取视频信息</span>
                  </div>
                  <article className="video-card">
                    <div className="video-cover">
                      {media.cover ? (
                        <img
                          src={"/api/v1/media/" + media.id + "/cover"}
                          alt={media.title}
                          onError={(e) => {
                            e.currentTarget.style.display = "none";
                          }}
                        />
                      ) : (
                        <div className="cover-placeholder">
                          <Film size={40} strokeWidth={1} />
                          <span>视频封面暂不可用</span>
                        </div>
                      )}
                      <span className="duration-label">
                        {duration(media.duration)}
                      </span>
                    </div>
                    <div className="video-details">
                      <div className="media-top">
                        <span>
                          {names[media.platform] || media.platform} · 视频
                        </span>
                        <span
                          className={
                            "watermark " +
                            (format?.watermark === "present" ? "warning" : "")
                          }
                        >
                          {format?.watermark === "absent" && (
                            <Check size={13} />
                          )}{" "}
                          {watermarkText}
                        </span>
                      </div>
                      <h3>{media.title}</h3>
                      <p className="byline">
                        {media.author ? "@" + media.author : "作者信息未提供"}
                        {media.duration != null
                          ? " · " + duration(media.duration)
                          : ""}
                      </p>
                      <div className="formats-heading">
                        <span>选择画质</span>
                        <span>
                          {format?.ext.toUpperCase()} ·{" "}
                          {format?.has_audio === true
                            ? "含声音"
                            : format?.has_audio === false
                              ? "无音轨"
                              : "音轨待校验"}
                        </span>
                      </div>
                      <div
                        className="formats"
                        role="group"
                        aria-label="选择画质"
                      >
                        {media.formats.map((f) => (
                          <FormatButton
                            key={f.id}
                            format={f}
                            active={selected === f.id}
                            disabled={processing}
                            onClick={() => {
                              setSelected(f.id);
                              setDownloadId(null);
                              setError("");
                              setNotice("");
                            }}
                          />
                        ))}
                      </div>
                      <p className="format-note">
                        {format?.watermark === "absent"
                          ? "平台未添加水印；作者原有的文字或标志可能保留。"
                          : format?.watermark === "present"
                            ? "该版本包含水印，保存时会保留。"
                            : "当前来源未提供可靠的水印标记，保存后请自行确认。"}
                      </p>
                      {processing && downloadJob && (
                        <JobProgress job={downloadJob} />
                      )}
                      {downloadConnection && processing && (
                        <p className="format-note">
                          连接暂时中断，正在恢复任务状态…
                        </p>
                      )}
                      {downloadJob?.status === "failed" && (
                        <p className="download-error" role="alert">
                          {downloadJob.error?.message}
                        </p>
                      )}
                      {expired(downloadJob) && (
                        <p className="format-note">
                          临时文件已过期，点击下方按钮可重新准备。
                        </p>
                      )}
                      {ready && (
                        <div className="ready-message" role="status">
                          <Check size={16} />
                          <span>
                            文件已就绪 · {bytes(downloadJob.result?.size_bytes)}
                            <small>
                              临时保留至{" "}
                              {new Date(
                                (downloadJob.result?.expires_at || 0) * 1000,
                              ).toLocaleTimeString("zh-CN", {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </small>
                          </span>
                        </div>
                      )}
                      <div className="download-actions">
                        {ready ? (
                          <>
                            <button
                              className="primary"
                              disabled={saving}
                              onClick={() => save(downloadJob)}
                            >
                              <Download size={17} />
                              {saving ? "准备保存…" : "保存到设备"}
                            </button>
                            <button className="text-button" onClick={prepare}>
                              重新准备
                            </button>
                          </>
                        ) : (
                          <button
                            className="primary"
                            disabled={processing || !format}
                            onClick={
                              sourceToReparse
                                ? () => retry(sourceToReparse)
                                : prepare
                            }
                          >
                            {processing ? (
                              <LoaderCircle className="spin" size={17} />
                            ) : (
                              <ArrowDown size={18} />
                            )}{" "}
                            {processing
                              ? "正在准备文件"
                              : sourceToReparse
                                ? "重新解析"
                                : downloadJob?.status === "failed"
                                  ? "重新准备"
                                  : format?.watermark === "absent"
                                    ? "准备无水印版本"
                                    : format?.watermark === "present"
                                      ? "准备带水印版本"
                                      : "准备下载"}
                          </button>
                        )}
                        {processing && downloadJob && (
                          <button
                            className="text-button"
                            onClick={() => cancel(downloadJob)}
                          >
                            取消
                          </button>
                        )}
                      </div>
                      <details className="details">
                        <summary>关于这个版本</summary>
                        <p>
                          从来源平台获取当前可访问的视频流，必要时合并音视频，不对画面做水印修复。画质与大小以实际文件为准。
                        </p>
                      </details>
                    </div>
                  </article>
                </div>
              </section>
            )}
            {!resolveId && !media && (
              <section className="how-section">
                <div className="content-width">
                  <div className="quiet-heading">
                    <h2>留住喜欢，只需三步。</h2>
                    <p>从链接到文件，自然顺畅。</p>
                  </div>
                  <div className="steps-grid">
                    <Step
                      number="01"
                      title="复制分享链接"
                      text="作品链接或整段分享文案，都可以。"
                      icon={<Link2 size={24} strokeWidth={1.4} />}
                    />
                    <Step
                      number="02"
                      title="选择可用画质"
                      text="看清画质与水印状态，再决定保存。"
                      icon={<Film size={24} strokeWidth={1.4} />}
                    />
                    <Step
                      number="03"
                      title="保存到设备"
                      text="文件准备好后，一键交给浏览器下载。"
                      icon={<Download size={24} strokeWidth={1.4} />}
                    />
                  </div>
                </div>
              </section>
            )}
          </>
        )}
        {view === "tasks" && (
          <section className="page content-width">
            <p className="eyebrow">留影 · 任务</p>
            <h1>
              每个片刻，
              <br className="mobile-break" />
              都在这里。
            </h1>
            <p className="page-copy">
              继续准备、重新保存，或处理未完成的任务。
            </p>
            <div className="filter-tabs" role="group" aria-label="任务筛选">
              {[
                ["all", "全部"],
                ["active", "处理中"],
                ["ready", "可保存"],
                ["failed", "未完成"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            {error && (
              <div className="inline-alert" role="alert">
                <AlertCircle size={18} />
                {error}
              </div>
            )}
            {taskItems.length === 0 ? (
              <div className="empty-surface">
                <Clock size={32} strokeWidth={1.3} />
                <h2>
                  {jobs.length
                    ? "暂时没有这类任务"
                    : "这里，等待你的第一个片刻。"}
                </h2>
                <p>解析和下载记录会保存在当前浏览器会话中。</p>
                <button
                  className="primary"
                  onClick={() => changeView("download")}
                >
                  去解析视频
                  <ChevronRight size={16} />
                </button>
              </div>
            ) : (
              <div className="task-list">
                {taskItems.map((job) => (
                  <article className="task-row" key={job.id}>
                    <span className={"task-icon " + job.status}>
                      {job.status === "running" || job.status === "queued" ? (
                        <LoaderCircle size={21} className="spin" />
                      ) : job.status === "ready" ? (
                        <Check size={21} />
                      ) : job.status === "cancelled" ? (
                        <X size={21} />
                      ) : (
                        <AlertCircle size={21} />
                      )}
                    </span>
                    <div className="task-info">
                      <h3>
                        {job.result?.filename ||
                          job.title ||
                          names[job.platform] +
                            " · " +
                            (job.kind === "resolve" ? "解析任务" : "下载任务")}
                      </h3>
                      <p>
                        {names[job.platform]} ·{" "}
                        {job.kind === "resolve"
                          ? "视频解析"
                          : job.quality || "视频下载"}{" "}
                        ·{" "}
                        {new Date(job.created_at * 1000).toLocaleString(
                          "zh-CN",
                          {
                            month: "numeric",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          },
                        )}
                      </p>
                      {job.error && (
                        <p className="task-error">{job.error.message}</p>
                      )}
                      {!terminal(job) && <JobProgress job={job} compact />}
                    </div>
                    <div className="task-actions">
                      <span className="task-status">
                        {expired(job)
                          ? "文件已过期"
                          : job.kind === "resolve" && job.status === "ready"
                            ? "已解析"
                            : stages[job.stage] || job.stage}
                      </span>
                      {!terminal(job) ? (
                        <button
                          className="text-button"
                          onClick={() => cancel(job)}
                        >
                          取消
                        </button>
                      ) : job.status === "ready" && job.kind === "download" ? (
                        <>
                          <button
                            className="small-primary"
                            disabled={saving || expired(job)}
                            onClick={() => save(job)}
                          >
                            保存
                          </button>
                          <button
                            className="icon-button"
                            onClick={() => retry(job)}
                            aria-label="重新准备文件"
                          >
                            <RefreshCw size={15} />
                          </button>
                        </>
                      ) : job.status === "ready" ? (
                        <button
                          className="text-button"
                          onClick={() => inspect(job)}
                        >
                          查看
                          <ChevronRight size={14} />
                        </button>
                      ) : (
                        <button
                          className="text-button"
                          onClick={() => retry(job)}
                        >
                          重试
                          <RefreshCw size={14} />
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
        {view === "platforms" && (
          <section className="page content-width">
            <p className="eyebrow">留影 · 支持平台</p>
            <h1>
              一个入口，
              <br className="mobile-break" />
              更多可能。
            </h1>
            <p className="page-copy">
              每个平台独立适配。作品权限、网络和平台变化，可能影响获取结果。
            </p>
            <div className="platform-list">
              {platforms.map((platform) => (
                <article className="platform-row" key={platform.id}>
                  <div className="platform-letter">
                    {platform.name.slice(0, 1)}
                  </div>
                  <div>
                    <h3>{platform.name}</h3>
                    <p>{platform.description}</p>
                  </div>
                  <span className={"platform-state " + platform.status}>
                    {platform.status === "available" && <span />}
                    {platform.label}
                  </span>
                </article>
              ))}
            </div>
            <div className="platform-footnote">
              <p>
                支持单条已发布视频。直播、DRM、图集和分片 HLS
                暂未开放；已接入不代表所有链接都能下载。
              </p>
              <button
                className="text-button"
                onClick={() => changeView("download")}
              >
                <ArrowLeft size={15} />
                返回下载
              </button>
            </div>
          </section>
        )}
        {notice && (
          <div className="notice" role="status">
            <Check size={16} />
            <span>{notice}</span>
            <button
              className="icon-button"
              aria-label="关闭通知"
              onClick={() => setNotice("")}
            >
              <X size={14} />
            </button>
          </div>
        )}
      </main>
      <footer>
        <div>
          <span className="footer-brand">留影。让喜欢，有处可留。</span>
          <span>
            单文件最高 {session ? bytes(session.limits.max_bytes) : "500 MB"} ·
            临时文件保留 1 小时 · 仅保存你有权使用的内容
          </span>
        </div>
        <div className="footer-bottom">
          <span>本地预览版 {session?.version || "0.1.0"}</span>
          <a
            href="https://media.w3.org/2010/05/sintel/trailer.mp4"
            target="_blank"
            rel="noreferrer"
          >
            公开样片来源
            <ArrowUpRight size={12} />
          </a>
        </div>
      </footer>
    </div>
  );
}

function FormatButton({
  format: f,
  active,
  disabled,
  onClick,
}: {
  format: Format;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className="format-option"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="format-title">
        {f.quality}
        {active && <Check size={13} />}
      </span>
      <span>
        {f.ext.toUpperCase()} ·{" "}
        {f.size_bytes ? "约 " + bytes(f.size_bytes) : "大小待确认"}
      </span>
      {f.watermark === "absent" && <small>平台无水印源</small>}
    </button>
  );
}
function Step({
  number,
  title,
  text,
  icon,
}: {
  number: string;
  title: string;
  text: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="step">
      <div className="step-top">
        <span>{number}</span>
        {icon}
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
function JobProgress({
  job,
  compact = false,
}: {
  job: Job;
  compact?: boolean;
}) {
  const p = job.progress;
  const percent =
    p.total_bytes && p.received_bytes != null
      ? Math.min(100, (p.received_bytes / p.total_bytes) * 100)
      : null;
  return (
    <div
      className={"job-progress " + (compact ? "compact" : "")}
      aria-live={compact ? "off" : "polite"}
    >
      <div>
        <span>{stages[job.stage] || job.stage}</span>
        {percent != null && <span>{percent.toFixed(0)}%</span>}
      </div>
      {percent != null && (
        <progress max="100" value={percent} aria-label="视频下载进度" />
      )}
      {p.received_bytes != null && (
        <small>
          {bytes(p.received_bytes)}
          {p.total_bytes ? " / " + bytes(p.total_bytes) : " · 大小待确认"}
          {p.speed_bps ? " · " + bytes(p.speed_bps) + "/s" : ""}
        </small>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
