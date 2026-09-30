# 专题调研:桌面/移动客户端类视频下载器的 UX 与功能设计参考

> 调研时间:2026-09-27。数据来源:GitHub REST API(直接读取,抓取当日数值)、各仓库 README/CHANGELOG/官方文档(经 raw/jsdelivr 抓取)、项目官网页面。凡未能实际抓到的数字一律标注"未核实"。
> 抓取留档:.research/ 目录(mediago 官方文档、Seal CHANGELOG、各 README、UI 截图等;截图因当前模型不支持读图未做人工分析)。

---

## 1. MediaGo(原 caorushizi/mediago,现 mediago-dev/mediago)

- **仓库**:https://github.com/mediago-dev/mediago (caorushizi/mediago 现已重定向至该 org)
- **Star**:9,251(万级;2026-09-27 API 实测)/ forks 823 / open issues 77
- **License**:MIT
- **技术栈**:TypeScript + Electron + React + Vite + Tailwind CSS + shadcn/ui;v3.x 起后端用 **Go 重写**(README 明示 "backend rewrite, lower memory footprint");仓库 topics 含 electron / hls / m3u8;发行物另含 Docker 镜像(amd64/arm64,Hub + GHCR)。repo 内 apps 目录结构:ui / server / player-ui / electron / core。
- **活跃度**:仓库创建于 2021-01-30;pushed_at 2026-09-24,updated_at 2026-09-26 —— 非常活跃。最新版本 v3.5.0(官方文档标注 2026-04-22 发布)。

### 核心功能清单
- **内置浏览器嗅探("资源提取")**:打开任意网页自动发现 m3u8/HLS、mp4 等媒体资源,无需抓包工具;支持沉浸式嗅探(资源手动确认入列 / 自动入列两种模式)。
- **多标签浏览页**:素材提取页支持多个独立标签,每个标签保留 URL、标题、前进后退历史、页面状态与嗅探结果互不干扰;Ctrl/Cmd+T 新建、Ctrl/Cmd+W 关闭、Ctrl+Tab 循环切换;标签仅存于当前会话,重启不恢复。
- **手动新建下载**:表单填入视频名称 + 流媒体(m3u8)/ 哔哩哔哩链接即可建任务。
- **多引擎**:yt-dlp(YouTube 及 1000+ 站点)、BBDown(哔哩哔哩)、N_m3u8DL-RE(HLS/m3u8)、aria2(直链),v3.5.0 新增 YouTube/1000+ 站点支持。
- **批量下载**与下载列表管理;下载列表可导出(纯文本,每行一个 URL);收藏列表导入/导出。
- **浏览器扩展(MV3,Chrome/Edge)**:跨站嗅探 HLS/m3u8、直连 mp4/flv/mov;识别 B 站与 YouTube 视频页/短片/直播/嵌入页;工具栏角标显示当前页检测到的资源数量;一键导入单条或全部资源。三种调用模式:URL Scheme 协议、HTTP 本地接口(127.0.0.1:39719)、远端 Docker 服务(可配 API Key)。导入行为可配置:立即开始下载 vs 仅入队;静默导入 vs 弹窗核对(名称/类型/路径)。
- **内置视频播放器**(桌面端 + 移动端网页播放)。
- **下载后格式转换**:应用内 ffmpeg 转格式/画质,无需另开工具。
- **开放 HTTP API + SSE 事件流 + CLI + MCP(11 个工具)+ OpenClaw Skill**(AI 编程助手自然语言发起下载)—— 桌面端 API 端口 39719,Docker 端 9900,统一 `/api` 前缀、统一 JSON 包裹 `{success, code, message, data}`。
- **Docker 部署 web 端**(8899 端口):局域网内手机/平板直接访问;Desktop 版默认同时监听 127.0.0.1 与局域网 IP。
- UI 内置中/英/意三语,浅色/深色主题;下载完成系统通知;关闭窗口可进系统托盘;自动更新(可选测试版)。

### 交互/技术设计亮点(对网页产品可直接借鉴)
- **任务状态机**:`waiting / downloading / success / failed / stopped`;SSE 事件 `download-create / download-start / download-success / download-failed / download-stop`(含失败 error 文案);支持按状态筛选、分页列出、批量改状态、单任务启停、查看任务日志。
- **解析(发现)是异步任务**:`pending / running / completed / failed / cancelled`,可取消;超时限制 3000–30000ms;结果内存保留约 10 分钟;解析结果与日志**不返回 Cookie/Authorization 等私密头**(隐私设计)。
- **设置分组清晰**:基础设置(目录/主题/语言/通知/控制台/更新/托盘)、浏览器设置(独立窗口、浏览器代理+开关、广告过滤、手机 UA 模式、沉浸式嗅探、隐私模式、清缓存)、下载设置(下载代理与浏览器代理**独立**、完成删除分片、最大并发 1–10、配置文件/可执行文件/存储路径)。
- **自动选最高清晰度**(v2.2.3 起),减少用户决策。
- **扩展失败不自动降级**,明确报错并提示切换模式(Schema 协议一次只能发一条任务,批量需切 HTTP 模式)—— 错误文案写清了原因与解法。
- **URL Scheme 唤起**:外部链接可直接唤起应用并添加下载任务(网页产品可对应"链接参数直达解析")。

### 优点
嗅探零门槛、桌面+Web(Docker)双形态、开放 API/SSE/MCP 生态(UI 只是 API 的一个消费者)、多引擎覆盖、中文界面与国内下载渠道(阿里/百度网盘兜底)。

### 缺点
扩展未上架商店需"加载已解压";页面嗅探依赖 Electron 浏览器执行器,纯 Docker/Core 部署无浏览器执行器时只能解析 m3u8(API 文档明确 `discovery_executor_unavailable`);标签会话重启即失;GPL 生态之外的使用场景受其免责声明约束(仅限学习研究)。

---

## 2. Seal(JunkFood02/Seal)—— Android 移动端标杆

- **仓库**:https://github.com/JunkFood02/Seal
- **Star**:29,238(3 万级;2026-09-27 API 实测)/ forks 1,436 / open issues 726
- **License**:GPL-3.0(另有条款:衍生品不得使用 Seal 名称)
- **技术栈**:Android 原生,Kotlin + Jetpack Compose,Material Design 3 动态取色;纯 Kotlin 单 Activity 无 Fragment;基于 yt-dlp + youtubedl-android,内嵌 aria2c。
- **活跃度**:创建于 2022-04-15;pushed_at 2026-09-25 —— 非常活跃;F-Droid 在架。

### 核心功能清单(README + CHANGELOG 实测)
- 基于 yt-dlp 下载视频/音频;aria2c 多线程外置下载。
- **格式/清晰度选择页(FormatPage)**:音视频条目带图标区分、无精确大小时显示近似大小、视频格式置底、长按显示流信息;支持视频裁剪(实验)、按章节分割。
- **音频**:提取音频并嵌入元数据+封面(mutagen)、合并多音轨。
- **字幕**:选择语言(含自动翻译字幕)、格式转换、嵌入视频、嵌入后保留字幕文件;记住上次字幕选择。
- **播放列表一键全下**(1.7.3 起上限 200 条)。
- **自定义命令模板**(yt-dlp 参数):创建/导入/导出/快捷方式、独立下载目录、任务仪表盘+日志页、命令内可直接插入 URL。
- **文件名**:默认输出模板 `%(title)s.%(ext)s`,支持自定义 `-o` 模板、`--restrict-filenames`、播放列表标题作为子目录。
- **Cookie 管理**:WebView 提取、刷新、导出文本、显示存储数量、可配 UA。
- **下载历史**:搜索、导入/导出(文件/剪贴板)、重新下载失效视频、**archive 记录跳过重复下载**。
- **Quick Download(快速下载)**:并行快速下载、自定义模板快捷方式、系统分享/Intent 接入、通知默认开启、图标角标显示运行任务数、下载目录扫描进系统媒体库、SD 卡支持。
- **网络**:代理配置、强制 IPv4、SponsorBlock 分类 chips、线程数 1–24、临时目录开关。
- **v2.0.0(未发布预览)**:并发下载、**下载队列**、失败/取消任务恢复、**队列备份与恢复**、Quick Download 中选格式/播放列表、大屏支持、预测性返回动画、最低 API 24。

### 交互设计亮点
格式选择页的信息密度与筛选(语言名/代码搜索字幕);长按=次要操作(选中/分享/Tooltip);底部弹层(MD3 ModalBottomSheet);错误处理的 UI 专项改进;触觉反馈;下载页取消按钮;模板/历史/设置全部可导入导出;无痕/隐私模式;深色/单色主题。

### 优点
移动端"粘贴/分享→解析→下载"的完整范式;模板与历史管理极细致;元数据/字幕/封面等"下载后体验"完备;分发渠道健康(F-Droid/GitHub Releases)。

### 缺点
仅 Android,无 Web/桌面形态;yt-dlp 更新时阻塞下载(历史已知问题);GPLv3 与名称保护条款对商业复用有限制;open issues 偏多(726)。

---

## 3. imwcr/EVDownloader —— 未找到,无法调研

实测结果:
- `api.github.com/repos/imwcr/EVDownloader` → **404**;
- GitHub 用户 `imwcr` 不存在(用户搜索无该账号;`user:imwcr` 仓库搜索返回 422"the resources do not exist")——附近账号 Imwcrj、imwcra 名下均无该项目;
- 仓库搜索 `EVDownloader`/`evdownloader` 仅命中无关项目(EduardoVeraE/evDownloader 2 stars、Azzlaer/EVDownloader_PRO 0 stars);
- gitee.com/imwcr → **404**。

**结论:该仓库不存在或已删除/改名/私有化,本次无法提供其功能与 UX 数据。** 移动端下载器参考由 Seal 覆盖(见上)。

---

## 4. 其他值得参考的 GUI 下载器(调研中补充发现)

### 4.1 Open Video Downloader(jely2002/youtube-dl-gui)

- URL:https://github.com/jely2002/youtube-dl-gui | 官网 https://jely2002.github.io/youtube-dl-gui/
- **Star**:9,289 / forks 661 / open issues 83;License **AGPL-3.0**;技术栈 **Rust + Tauri + Vue 3 + TypeScript**;Win/macOS/Linux,Microsoft Store / Homebrew / WinGet 分发;pushed_at 2026-09-13,活跃。
- 核心功能:视频/音频下载;**字幕与元数据自动保存**;清晰度/帧率/封装格式(MP4/MKV)选择;**整播放列表下载**;自定义保存位置与**文件名模板**;官网宣称 1000+ 站点、最多 **32 并行下载**、**20+ 设置项**;"smart queueing"(自动平衡多下载以不拖慢机器);Cookie 文件/基础认证/视频密码;应用与 yt-dlp 自动更新;明暗主题;快捷键与通知。
- 借鉴点:文件名模板 + 预设;并行上限高且"智能"调度;下载进度与错误展示清晰。

### 4.2 youtube-dlg(MrS0m30n3/youtube-dl-gui)—— 经典但已停更

- URL:https://github.com/MrS0m30n3/youtube-dl-gui
- **Star**:9,428 / forks 1,576;License **The Unlicense**;技术栈 Python + wxPython,跨平台;last pushed **2022-12-06,已停更**(社区 fork oleksis/yt-dlg 接手维护,其 README 抓取失败,内容未核实)。
- 功能(README 实测):youtube-dl 的跨平台 GUI;可选 FFmpeg 后处理;多语言。其经典的"任务队列 + 逐条状态显示"式界面是同类产品鼻祖,但具体队列交互细节(暂停/重试按钮等)本次未抓到一手资料,**标为未核实**。
- 借鉴点:此类产品的"老式队列"UI 已演化为今日任务列表的标配,可直接参考现代继任者(OVD/omniget)。

### 4.3 OmniGet(tonhowtf/omniget)—— 下载体验细节密度最高的新秀

- URL:https://github.com/tonhowtf/omniget
- **Star**:14,392 / forks 1,265 / open issues 3;License **GPL-3.0**;技术栈 **Rust(Tauri 桌面)+ WebKitGTK(Linux)**;Win/macOS/Linux(安装版/便携版/MSI/AppImage),winget/brew 分发;创建于 2026-02-11,pushed_at 2026-09-26 —— 极活跃。
- 定位一句话:**"Paste a link, see a preview with quality options, click download"** —— 与本次产品形态最接近(单输入框 → 预览(标题/缩略图/清晰度)→ 下载)。
- 下载相关核心功能(README 实测):
  - yt-dlp + FFmpeg **自动安装**(SHA-256 校验)与自动更新,零配置;
  - Downloads 页显示**速度/阶段/ETA 真实读数**,"卡住的下载看起来就是卡住,而不是停在 3 秒剩余";
  - **断点续传**;失败**重试带 backoff**;**按站点自适应并发**(YouTube 最多 16 并行分片,对返回 429 的站点自动降低并发);
  - 每条任务**保留其执行的精确 yt-dlp 命令,可编辑后重试**;
  - **全局热键**:Ctrl/Cmd+Shift+D 读剪贴板后台下载、Ctrl/Cmd+Shift+M 仅音频(可改键、默认关闭);
  - **浏览器扩展**:支持站点一键转发 + 其余站点网络嗅探(MP4/HLS/DASH/WebM/音频);转发 Cookie/referer 以支持登录内容;**Cookie 按真实站点分组**;YouTube "Force H.264" 开关;Deep search(钩页面播放器抓不产生网络请求的资源);HLS 流大小预估;音视频轨配对合一;**首字节校验防止把 HTML 错误页存成视频**;捕获规则可编辑;本地配对 token(仅 127.0.0.1:47720–47729);
  - "设置一次":默认质量、音频格式(MP3/M4A/Opus/FLAC/WAV)、字幕语言与格式(SRT/VTT/ASS/内嵌/sidecar)、缩略图与元数据嵌入、**文件名模板**、按平台归档、跳过已存在文件、按章节分割、限速、并发数、代理;
  - **规则引擎**:指定频道/域名 → 指定文件夹+画质,之后不再询问;关注频道后台检查新更+托盘通知;
  - 原生解析器覆盖课程(Udemy/Hotmart/Rocketseat)、Instagram/TikTok/X/Pinterest/Reddit、Bilibili(弹幕 XML/ASS/JSON、NFO 供 Kodi/Jellyfin、11 种链接类型)、gallery-dl(250+ 画廊站)、Torrent/磁力、直链 HLS/DASH、Telegram;其余 1800+ 站走 yt-dlp;内置播放器;便携模式(全部数据跟目录走)。
- 优点:进度真实性、自适应并发、可编辑命令重试、热键直下、嗅探扩展细节(配对/校验/分组)密度最高。缺点:定位是"下载器+156 个工具+AI agents"的万能箱,超出纯下载器范畴;项目仅 7 个月历史,稳定性与生态待观察;GPL-3.0。

### 4.4 Bili23-Downloader(ScottSloan/Bili23-Downloader)—— 单站深挖的交互教科书

- URL:https://github.com/ScottSloan/Bili23-Downloader | 官网 https://bili23.scott-sloan.cn/
- **Star**:7,763 / forks 563 / open issues 12;License **GPL-3.0**;技术栈 Python + **PySide6**(Fluent 风格);Win(含 Win7)/Linux/macOS;pushed_at 2026-09-26 —— 极活跃。
- 核心功能(README 实测):
  - 全类型解析:B 站投稿/番剧/电影/课程/互动视频/音乐(au/am)/UP 空间/收藏夹/每周必看/订阅合集/追番追剧/稍后再看/历史记录;
  - **一次粘贴多条链接批量解析**;空间/收藏夹等支持**关键词搜索**(当前页或全部);
  - **解析后按预设条件自动勾选**下载项;
  - 多线程并行 + **断点续传 + 网络异常自动重试** + 全局限速;
  - 画质 8K/4K/HDR/杜比视界,音质 Hi-Res/杜比全景声,编码 AVC/HEVC/AV1;**下载前实时预览**将下载的媒体;
  - 弹幕 xml/ass/json、字幕 srt/lrc/txt/ass/json、自定义样式、ass 嵌入 mkv;
  - 封面无损保存(jpg/png/avif/webp)与嵌入、章节写入;**NFO 元数据刮削**(Kodi/Jellyfin/Emby 标准);
  - **命名模板 + 多级目录分类规则引擎**(按内容类型分别配置);
  - mp4/mkv 封装;**重复下载检测**(记录历史,再下同内容提示并可直接跳过);
  - **三种代理模式**(不使用/系统/手动)+ 按地域选 CDN + 自定义 UA/Host;
  - **剪贴板监控**:复制 B 站链接自动识别并确认后进入解析;
  - 扫码/短信/Cookie 登录;浅深主题、窗口大小位置记忆、高分屏适配;多语言(简中/繁中/EN)。
- 优点:自动勾选、命名规则引擎、重复检测、剪贴板监控、断点续传+重试——单站产品把"解析→选择→命名→下载→归档"整条链路的 UX 做透了。缺点:仅限 B 站,泛化需改造。

---

## 5. 总结:对"网页端粘贴链接 → 解析 → 下载"产品的可借鉴清单

### A. 输入与解析阶段
- **单一主输入框**(omniget 的"one text box"哲学),支持一次粘贴多条链接/多行/导入 txt(mediago 批量、Bili23 批量解析、omniget Bulk)。
- **粘贴即解析、解析出预览**:展示标题、封面缩略图、清晰度/格式列表供选择(omniget "preview with quality options";Seal FormatPage);默认自动选最高清晰度(mediago)。
- **解析是异步任务**:显示阶段状态(pending/running/completed/failed)、可取消、有超时上限(mediago:3–30s)、结果短暂缓存;不支持的平台/模式给**明确原因型错误文案**(mediago `discovery_executor_unavailable`)。
- **多渠道入口**:剪贴板监控(Bili23)、全局热键读剪贴板(omniget Ctrl+Shift+D/M)、URL Scheme 直达(mediago)、系统分享菜单/Intent(Seal)。网页产品对应:链接参数直达解析 + 移动端分享到网页 PWA。
- **解析进度反馈**:嗅探/解析期间显示"正在解析/发现 N 个资源"的中间态与资源数量角标(mediago 扩展角标)。

### B. 选择与配置阶段
- **清晰度选择器**:分辨率 + 编码(AVC/HEVC/AV1)+ 帧率 + **文件大小预估**(Seal 近似大小、Bili23 实时预览),音视频分离与合并说明,音频-only 选项及音频格式(MP3/M4A/Opus/FLAC/WAV)。
- **记住用户偏好**:上次质量/字幕选择(Seal)、"设置一次不再问"(omniget)、按平台归档/跳过已存在。
- **默认文件名规则**:默认 `%(title)s.%(ext)s`,提供模板变量(标题/上传者/日期/播放列表/序号/子目录),支持 restrict-filenames 与自动去重(Bili23 重复检测、Seal archive)。
- **批量自动勾选**:解析列表出来后按预设条件自动勾选目标项(Bili23)。

### C. 下载任务管理(核心)
- **任务列表 + 状态机**:waiting/downloading/success/failed/stopped;单任务启停/删除/编辑/改名/改目录;批量改状态;按状态筛选、分页(mediago API)。
- **真实进度**:速度/阶段/ETA 取下载器真实读数,不做假进度;卡住如实显示(omniget);用 SSE/WebSocket 推送(mediago `/api/events`),失败事件携带**可读 error 文案**。
- **并发与队列**:最大并发可配置(mediago 1–10;OVD 最多 32;omniget 按站点自适应并发、对 429 降并发),其余任务排队等待。
- **失败处理**:自动重试带 backoff(omniget)、失败/取消任务可恢复重下(Seal v2.0)、**断点续传**(omniget/Bili23)、保留并允许编辑"实际执行的命令"重试(omniget)。
- **每任务日志/控制台**:可展开查看原始日志(mediago logs、Seal 日志页),错误可排查。
- **完成反馈**:系统通知/角标/托盘(mediago、Seal 角标、omniget 托盘),移动端推送。
- **历史记录**:搜索、导入导出、重复下载检测与跳过、失效重下(Seal/Bili23)。
- **下载后动作**:内置播放预览(mediago/omniget)、转码/格式转换/音频提取(mediago、Seal)。

### D. 移动端与响应式适配
- 大屏/平板布局(Seal v2 large screen support);移动端浏览器直接播放已下载内容(mediago Docker 局域网访问);
- 触屏交互规范:长按=次要操作、底部弹层承载选项(Seal MD3)、移动端"分享→解析→一键下载"最短路径。

### E. 网络与环境设置
- **代理设置**:浏览器解析代理与下载代理**分开开关**(mediago);无/系统/手动三档(Bili23);自定义 UA/Host。
- 限速、并发数、临时目录、完成后清理分片(mediago deleteSegments)。
- Cookie/登录态管理:WebView 提取、按站点分组、导出(Seal/omniget),且**凭据不落前端响应、不写库**(mediago 隐私设计)。

### F. 开放接口与生态(网页产品可选)
- 把核心能力暴露为 HTTP API + 事件流,让 UI、浏览器扩展、脚本、AI 助手成为同一套 API 的消费者(mediago:扩展/CLI/MCP/Skill 全部走 API)—— 未来做浏览器扩展或第三方接入时零改造。

### G. 信任、合规与分发文案
- 免责声明 + "仅限个人学习研究"提示(mediago/Bili23/OVD);明确不绕过 DRM/付费墙/站点访问控制;
- 首次使用的引导成本控制:自动安装与自校验依赖(omniget SHA-256)、无命令行(OVD "No command-line setup required")、引导式图文步骤(mediago 官方文档 guides)。
- 多语言(中/英优先)+ 浅/深主题几乎成为标配。

---

## 附:数据来源与备注
- GitHub API 实测(2026-09-27):mediago-dev/mediago、JunkFood02/Seal、jely2002/youtube-dl-gui、MrS0m30n3/youtube-dl-gui、tonhowtf/omniget、ScottSloan/Bili23-Downloader 的 star/forks/license/语言/pushed_at。
- 一手文档:mediago README + docs/{guides,documents,extension,api,changelog}.md;Seal README + CHANGELOG.md + fastlane 应用描述;OVD README + 官网;omniget README;Bili23 README。
- EVDownloader(imwcr):GitHub 与 Gitee 均 404,用户 imwcr 不存在,按"未找到"处理。
- 未核实项:youtube-dlg 的队列交互细节(项目停更、README 未载);各项目"下载量"数据;OVD"最多 32 并行/20+ 设置"为其官网宣传数字,未做独立验证。
