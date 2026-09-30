# 调研报告:「Web 服务 / API 形态」视频下载同类产品

> 调研专题:粘贴链接 → 解析 → 无水印下载的 Web 服务与下载 API 包装项目
> 调研员:独立调研子代理 · 日期:2026-09-26
> 数据来源:api.github.com 仓库元数据(实测)、各仓库 README / docs(实测抓取,标注 URL)、web_search 交叉验证。抓不到的字段一律标注「未核实」。

---

## 〇、数据获取说明(可信度)

- 本次通过 api.github.com 实测拿到 6 个指定仓库的 **star 数 / license / 主语言 / pushed_at(最近推送时间)**,数值可信(抓取时点:2026-09-26)。
- 各项目 README 与核心文档(cobalt 的 docs/api.md、protect-an-instance.md、api-env-variables.md、api/README.md、web/README.md;Douyin_TikTok_Download_API 的 README.md 与 documents/en/11-api.md;metube 的 README.md 与 pyproject.toml;yt-dlp-web-ui / alltube / Parabolic / YoutubeDL-Material / dler 的 README)均已实际抓到原文,下文架构描述均出自这些原文。
- 抓取环境限制:github.com 网页与 raw.githubusercontent.com 在本环境断断续续,部分字段(如 YoutubeDL-Material 活跃度)标注「未核实」。

---

## 一、imputnet/cobalt(cobalt.tools)★ 重点对标对象

| 项目 | 信息 |
|---|---|
| 仓库 | https://github.com/imputnet/cobalt |
| Star | **43,839**(约 4.4 万;forks 3,842)实测 |
| License | API 部分 **AGPL-3.0**;前端(web/)为 **CC-BY-NC-SA-4.0**(禁止商用,品牌资产另有版权,自托管需保留或替换品牌)——双许可证,商业化需特别注意 |
| 技术栈 | monorepo:`api/` = Node.js/TypeScript + **Express.js**;`web/` = **SvelteKit + Vite** 静态前端;依赖 **ffmpeg**(服务端转封装/转码)、**youtube.js**(LuanRT,对接 YouTube Innertube API)、undici、hls-parser、zod(请求 schema 校验)、express-rate-limit;前端用 **libav.js**(ffmpeg 编译到 WASM)做浏览器端 remux/编码 worker |
| 数据库 | **无数据库**。隧道(tunnel)信息只存内存,TTL 90 秒(TUNNEL_LIFESPAN),用优先级队列做内存缓存清理("without redis");多实例横向扩展时才引入 Redis(API_REDIS_URL + API_INSTANCE_COUNT) |
| 活跃度 | 实测 pushed_at = **2026-04-06**,非常活跃;创建于 2022-07;官网 cobalt.tools 运营中 |

### 1.1 完整链路设计(实测 docs/api.md + api/README.md)

1. **前端提交**:单输入框粘贴链接,POST 到实例主端点 `POST /`,JSON body:`url`(必填)+ 可选 `downloadMode(auto/audio/mute)`、`videoQuality(max/4320/…/144)`、`audioFormat(best/mp3/ogg/wav/opus)`、`audioBitrate`、`filenameStyle`、`disableMetadata`、`localProcessing(disabled/preferred/forced)`、`subtitleLang`,以及服务专属项(`youtubeVideoCodec=h264/av1/vp9`、`youtubeVideoContainer`、`allowH265`(TikTok)、`tiktokFullAudio`、`convertGif` 等)。前端还支持 `#` 后直接带链接预填(cobalt.tools/#https://…)。
2. **后端解析**:**全自研解析器**,每个服务一个模块(services/),用 `url-pattern` 匹配链接、`undici` 直连平台 API/CDN。YouTube 走 youtube.js(Innertube API);TikTok/Instagram/Twitter/VK/SoundCloud/Bilibili 等各自自研。**不包装 yt-dlp。**
3. **响应状态机**(一次 POST 返回以下之一):
   - `redirect`:直接 302 到平台原始直链(省服务器流量);
   - `tunnel`:cobalt 代理/转封装/转码,返回自身 `/tunnel` 流式地址;
   - `picker`:一条链接里有多媒体(如 Instagram 轮播、TikTok 图文)时返回条目列表让前端弹选择器;
   - `local-processing`:服务端只代理原始分片,由浏览器端 libav.js 在本地合并/静音/转码(可强制:FORCE_LOCAL_PROCESSING),显著省服务器 CPU;
   - `error`:机器可读错误码。
4. **文件回传**:`GET /tunnel` 直接**流式回传文件**;带 `Content-Length`(精确)或 `Estimated-Content-Length`(估算,供 UI 进度条)。**不落盘、不缓存内容**——官方原话:"cobalt never caches any content, it works like a fancy proxy"。
5. **m3u8/合并/清晰度/音频**:依赖 **ffmpeg** 做 muxing/encoding(ffmpeg 子进程,可用 PROCESSING_PRIORITY=nice 降优先级);**hls-parser** 解析 HLS 播放列表(YouTube HLS 模式已标记 deprecated);清晰度选择、音视频分离(downloadMode=mute/audio)、封面裁剪、TikTok 原声提取(tiktokFullAudio)、Twitter GIF 转换均支持。YouTube 支持 8K/4K/HDR/VR、h264/av1/vp9、dub 音轨。
6. **支持的平台**(实测 api/README.md 表格):bilibili、TikTok、YouTube、Instagram(含 reels/图文)、Twitter/X、Facebook、Reddit、SoundCloud、Vimeo、VK、Pinterest、Twitch clips、Snapchat、Tumblr、Bluesky、Dailymotion、Loom、Newgrounds、ok.ru、Rutube、Streamable 等 20+ 个。**国内平台只有 B 站,不支持抖音/快手/小红书。**
7. **API 形态**:REST JSON(`POST /`、`POST /session` 换 JWT、`GET /` 实例信息、`GET /tunnel` 取流)。**官方不提供公共托管 API**,只自托管;官方实例 api.cobalt.tools 开 Turnstile 且不允许第三方项目白嫖。

### 1.2 防滥用设计(实测 protect-an-instance.md + api-env-variables.md,这是同类最强)

- **Cloudflare Turnstile**(隐形验证码)+ **JWT Bearer 短期 token**(JWT_EXPIRY 默认 120s);
- **API Key 文件**(keys.json):每把 key 可配 `limit`(窗口内请求数/`"unlimited"`)、`ips`(IP/CIDR 白名单)、`userAgents`(UA 通配)、`allowedServices`;`API_AUTH_REQUIRED=1` 可强制全站鉴权;
- **分级限流**:普通请求 RATELIMIT_WINDOW=60s / RATELIMIT_MAX=20 次(按 IP hash);session 换取、tunnel 下载各有独立限流(TUNNEL_RATELIMIT_MAX=40);响应带标准 `RateLimit-*` 头;
- `DURATION_LIMIT`(默认 10800s=3 小时)限制超长视频;`DISABLED_SERVICES` 按服务开关;`CORS_WILDCARD/CORS_URL` 控跨域;
- `FREEBIND_CIDR`:每次下载随机换出口 IPv6(反平台风控);`cookies.json` 支持需要登录才能看公开内容的平台;`YOUTUBE_SESSION_SERVER` 对接 yt-session-generator 自动刷 YouTube poToken/visitor_data;
- 部署:Docker Compose + watchtower 自动更新,官方建议前面再挂 nginx 反代。

### 1.3 无水印能力

官方文档口径(api/README.md 支持矩阵):**TikTok「supports videos with or without watermark, images from slideshow without watermark, and full (original) audios」**——即从平台返回的候选流里**直接挑选无水印 CDN 地址**(干净流),而不是对视频像素做去水印处理。同时 `allowH265`、`tiktokFullAudio` 提供选项。对抖音(国内版)不支持。

### 1.4 优点 / 缺点 / 风险 / 借鉴

- **优点**:① 无存储、无账号、零运维负担的「高级代理」哲学,隐私与合规姿态好;② 防滥用体系(限流/验证码/API key 分权)是同类标杆;③ 响应状态机(tunnel/redirect/picker/local-processing)优雅,本地处理把转码 CPU 摊到用户浏览器;④ 前端与 API 解耦,前端纯静态可单独托管,API 可商用前端替换;⑤ 支持平台广且质量高(YouTube 8K/HDR)。
- **缺点**:① 自研解析器维护成本极高,平台风控一改就要发版;② 不支持抖音/快手/小红书(国内仅 B 站);③ 无公共 API、无持久化(不适合做"下载历史/任务中心"型产品);④ 前端 CC-BY-NC 禁止商用 + AGPL 传染,白标/商业场景要重写前端。
- **风险**:依赖平台接口稳定性与 YouTube 的 poToken 机制;实例暴露公网若不加 Turnstile 会被脚本刷爆(官方文档专门教你怎么防)。
- **借鉴点**:POST / 的 JSON schema 与状态机设计、`Estimated-Content-Length` 进度方案、ip-hash 限流 + Turnstile + 分级 API key、浏览器端 libav.js 合并省服务器、tunnel 短 TTL 内存化。

---

## 二、Evil0ctal/Douyin_TikTok_Download_API(抖音/TikTok 下载 API)★ 重点对标对象

| 项目 | 信息 |
|---|---|
| 仓库 | https://github.com/Evil0ctal/Douyin_TikTok_Download_API(org 名首字母小写 evil0ctal) |
| Star | **20,343**(约 2 万;forks 2,821)实测 |
| License | **Apache-2.0**(明确允许商用/闭源使用,作者仅以赞助方式回馈) |
| 技术栈(v5 实测 README) | Python 3.12 + **FastAPI** + SQLAlchemy 2.0(async)+ Alembic + Typer + structlog;传输层 **wreq**(浏览器 TLS 指纹模拟)+ httpx;**PostgreSQL + TimescaleDB** 归档、**Redis** 队列/缓存;**React 19** 控制台(Vite/TanStack Query/wouter/i18next);签名算法 a_bogus / X-Bogus / X-Gnarly / X-Dynosaur **纯 Python 实现**+浏览器回退;身份铸造用 **CloakBrowser 无头浏览器**(独立容器,HTTP RPC);**下载器是 Go 1.23 纯标准库 sidecar**(scratch 镜像);鉴权 argon2id + 带 scope 的 API key;入口:REST(93 个端点)+ **MCP**(streamable-http)+ CLI |
| 数据库 | PostgreSQL(+TimescaleDB)全量归档 + Redis(队列、缓存、限流计数) |
| 活跃度 | 实测 pushed_at = **2026-09-23**,非常活跃;创建于 2021-11;官网 douyin.wtf、在线 demo demo.douyin.wtf(限流 30 次/10s) |

### 2.1 版本背景:从 v4 到 v5 的重写(实测 README 的 v4 vs v5 对照表)

- **v4(历史)**:同步请求(发完就等)、PyWebIO 单页界面、身份来自用户从浏览器拷贝 cookie 填 config.yaml、**无任何存储**(解析完即弃)、X-Bogus/A_Bogus 签名、支持抖音/TikTok/B 站。**核心痛点:API 会"静默死亡"**——cookie 过期、签名算法变更、接口被限流,没人知道,直到有人来提 issue。
- **v5(当前 main)**:异步任务(202 + task_id)、**自愈身份池**(无头浏览器自动铸造游客身份,不够用自动补充)、健康分层 + 量化 LRU 轮换 + 每身份一在飞锁 + 每(身份×端点)令牌桶 + 每端点熔断器、全量 PostgreSQL 归档、React 控制台、REST+MCP+CLI 三入口、纯 Python 四套签名 + 浏览器回退。**平台覆盖收敛为抖音 + TikTok**(B 站被砍掉待补)。

### 2.2 完整链路设计(实测 documents/en/11-api.md,细节极其完整)

1. **前端提交**:React 控制台的 Playground 粘贴链接;或直接调 `POST /api/v1/parse`,body `{"url": "..."}`。支持短链(v.douyin.com / vm.tiktok.com)、整段分享文案(链接埋在文案里自动提取)、甚至裸 aweme_id。**URL 白名单校验在入口完成**,不合法的主机直接 400 拒绝,不花上游请求。
2. **异步任务模型(核心)**:默认异步——API 容器只做校验、入队、立刻回 `202 {"task_id": "...", "state": "queued"}`;**API 容器本身从不直接访问平台**,由 worker 执行。取结果三种方式:①轮询 `GET /api/v1/tasks/{task_id}`;②`?wait=N` 同步等待(上限 30s);③`callback_url` webhook(默认关闭,HTTPS+非私网+HMAC 签名,严格防 SSRF)。另提供 SSE 事件流(`/tasks/{id}/events`)供前端实时刷新;批量子任务 `POST /api/v1/tasks/batch` 一次 50 条。
3. **调度与风控层(自愈身份池)**:worker 用池化的游客身份发请求:健康分层、LRU 轮换、每身份一在飞锁、每(身份,端点)令牌桶、每端点熔断器;每个请求留结构化记录、身份与端点健康状态在控制台实时可见——解决 v4「静默死亡」问题。
4. **解析**:平台适配器(platforms/)用纯 Python 签名(a_bogus/X-Bogus/X-Gnarly/X-Dynosaur)构造请求,`?explain=` 可回放签好名的原始请求(调试用,需 operator 角色);解析结果归一化为统一内容模型(models/),**全量归档进 PostgreSQL/TimescaleDB**(上游删帖本地仍在)。
5. **下载**:媒体下载由 **Go sidecar 下载器**执行(独立容器、scratch 镜像);支持按作者批量下载、跳过已有、重复清理;文件存运营商磁盘,回传 `GET /api/v1/downloads/{download_id}/files/{name}`(带 Content-Disposition)。
6. **清晰度/音频/m3u8**:API 返回的是平台各档清晰度与无水印流的元数据,客户端/下载器按需取流(README 未宣称 ffmpeg 合并 m3u8 的具体细节——**未核实**该环节的实现粒度;Go 下载器职责为取媒体文件)。
7. **缓存与合并**:相同请求 90s 内 coalescing(合并到一个上游请求);响应缓存 content 30min / author 15min / list 5min(Redis,`meta.cached` 标记);任务结果保留 24h 后清空。
8. **限流/防滥用**:API key 带 scope(`douyin:read`/`tiktok:read`/`archive:export`/`media:write`/`identity:manage`/`admin`)与角色(demo<viewer<operator<admin);每 key 每分钟限流(默认 120 次/min,可在 1–100000 间定制,标准 X-RateLimit-* 头);队列上限 500(满则 503 QUEUE_FULL + Retry-After);请求体上限 1MiB;匿名端点按客户端 IP 计费并默认关闭 CORS;webhook/代理参数均有 SSRF 栅栏。
9. **部署**:`docker compose up`(api / worker / downloader 三镜像 + 可选 browser 侧车),amd64/arm64;一键安装脚本(兼运维菜单:升级/备份/清理);裸机 systemd 文档;国内镜像准备说明;反向代理与 TLS 指南。

### 2.3 无水印能力

官方 README 原话:**「downloads video and image albums without a watermark (it picks the clean stream the platform already publishes rather than stripping anything)」**——即通过带签名的平台接口拿到平台本就发布的无水印流地址(选择干净流,而非像素级擦除水印)。这是国内同类项目最主流的路数:v4 时代同样是通过平台 API 的 play 地址选择无 watermark 流。

### 2.4 优点 / 缺点 / 风险 / 借鉴

- **优点**:① 国内平台(TikTok/抖音)解析能力最强、最工程化,身份池自愈 + 令牌桶 + 熔断是生产级设计;② Apache-2.0 可商用,门槛低;③ 异步任务 + SSE + webhook + 归档 + MCP/CLI,几乎是一套完整的数据中台;④ 可观测性(每请求结构化日志、健康面板、?explain= 回放)业界罕见;⑤ Docker 三镜像部署简单。
- **缺点**:① 平台覆盖面窄(v5 只有抖音/TikTok,B 站被砍,快手/小红书不在 v5);② 依赖签名逆向,平台每改一次算法就可能失效(靠自愈身份池 + 浏览器回退缓解);③ 复杂度高(Postgres+TimescaleDB+Redis+无头浏览器+Go 下载器),自托管资源门槛高于 cobalt;④ 数据归档使产品承担更多存储/合规责任。
- **风险**:国内平台风控升级、签名算法变更、法律合规(抓取与归档个人数据);demo 实例本身 30 次/10s 限流说明开放公网服务的滥用压力。
- **借鉴点**:**异步任务协议(202+task_id+SSE+webhook)、自愈身份池 + 令牌桶 + 熔断、请求合并与分层缓存、scope 化 API key、URL 入口白名单、?explain= 调试回放、MCP 入口**——做「国内平台解析服务」几乎是直接可抄的答案。

---

## 三、marcopiovanello/yt-dlp-web-ui(任务书中的 MarcelloCuoghi 仓库,已迁移)

| 项目 | 信息 |
|---|---|
| 仓库 | https://github.com/marcopiovanello/yt-dlp-web-ui(原 MarcelloCuoghi/yt-dlp-web-ui → 曾为 marcopeocchi/yt-dlp-web-ui,现名,api.github.com 实测重定向确认) |
| Star | **2,589** 实测;License **GPL-3.0**;主语言 **Go** |
| 活跃度 | 实测 pushed_at = **2026-08-21**,活跃;创建于 2021-11 |

### 3.1 架构要点(实测 README)

- 定位自述:"A terrible web ui and RPC server for yt-dlp. Designed to be self-hosted."——单二进制 Go 服务,面向 NAS/树莓派低资源场景。
- **前端提交**:内嵌前端(构建目录含 `web/solid-frontend`,即 **SolidJS**,实测自配置文件注释)+ 自定义前端加载(frontend_path);设置项含服务端地址、主题、音频提取、可选格式选择(默认关,追求自动最佳质量)、输出文件名/路径覆盖、自定义 yt-dlp 参数(安全传递)、**下载队列(并发上限)**。
- **解析/下载**:**包装 yt-dlp**——`--driver` 指定 yt-dlp 可执行路径,服务端 fork 子进程执行;`--qs` 控制并发数(flag 默认 2,config 默认逻辑核数);SQLite 本地库(默认 `local.db`)存会话/元数据;监控直播(livestream)是作者的核心场景。
- **协议**:**JSON-RPC 1.0** 走 WebSocket 与 HTTP-POST;`/openapi` 提供 Swagger;计划中的 gRPC;JWT 鉴权(--auth + --user/--pass + JWT_SECRET)。
- **部署**:Docker(marcobaobao/yt-dlp-webui、ghcr.io)、AWS/DigitalOcean/Render 一键部署按钮、预编译二进制、systemd、Nix。
- **优点**:极轻量、RPC 接口利于集成/自写前端;局限:功能围绕"帮我下到 NAS"而非公网服务,无内置限流/防滥用(靠部署边界),GPL-3.0 传染。

---

## 四、alexta69/metube

| 项目 | 信息 |
|---|---|
| 仓库 | https://github.com/alexta69/metube |
| Star | **14,856** 实测;License **AGPL-3.0**;主语言 Python |
| 活跃度 | 实测 pushed_at = **2026-09-26**,极活跃;创建于 2019-11 |

### 4.1 架构要点(实测 README + pyproject.toml)

- **后端框架**:pyproject.toml 实测依赖 `aiohttp` + `python-socketio`(+yt-dlp[default,curl-cffi,deno]、mutagen、curl-cffi、watchfiles)——即 **aiohttp 后端 + Socket.IO 实时进度推送**(第三方评测页曾称"likely Flask",以 pyproject 为准)。前端为随镜像内置的网页(未声明框架,未核实)。
- **链路**:粘贴链接 → 后端入队(应用内队列,**MAX_CONCURRENT_DOWNLOADS 默认 3**,其余排队)→ 子进程跑 **yt-dlp**(纯包装,无自研解析)→ 文件写 `/downloads` 卷(支持输出模板、TEMP_DIR、AUDIO_DOWNLOAD_DIR 分目录)→ 完成后通过 `/download/`、`/audio_download/` 路由回传文件(PUBLIC_HOST_URL 可指向外置存储)。
- **功能**:视频/音频/字幕/缩略图、播放列表/整频道、**订阅**(定时检查频道与播放列表新更,自动入队)、yt-dlp 选项三层配置(全局 YTDL_OPTIONS → 预设 → 单次覆盖)、上传浏览器 cookie(私有/年龄限制视频)、yt-dlp nightly 自动更新、硬件加速转码(文档/wiki 提供 GPU 配方)。
- **安全**:无内置登录/限流(README 明确)——靠反代加认证;**SSRF 防护**(ALLOW_PRIVATE_ADDRESSES 默认 false);CORS 白名单;DOWNLOAD_DIRS_INDEXABLE 默认关。
- **优点**:定位清晰「只管把文件下到盘里」,自托管生态最好(wiki 配方、watchtower 更新、多架构镜像);**缺点/风险**:单实例无多租户、无审计、无内置限流,AGPL 网络服务条款;公开部署需自行加认证层。**借鉴**:Socket.IO 进度推送、订阅自动下载、三层 yt-dlp 选项模型。

---

## 五、Rudloff/alltube(已归档,历史参照)

| 项目 | 信息 |
|---|---|
| 仓库 | https://github.com/Rudloff/alltube |
| Star | **2,965** 实测;License **GPL-3.0**;主语言 PHP |
| 活跃度 | 实测 pushed_at = **2023-04-22**,**archived: true(已归档停止维护)**,创建于 2014-03 |

- **架构**(实测 README):PHP 7.2+ + Smarty 模板 + Composer;包装 **youtube-dl**(不是 yt-dlp);ffmpeg 可选(默认关闭转换);**JSON API**:`/json?url=…` 直接返回 youtube-dl 的 JSON 元数据;核心 `Video` 类拆为独立 composer 包 rudloff/alltube-library 可复用;支持 Heroku/Cloudron 一键部署、X-Forwarded-* 反代头。
- 意义:youtube-dl Web GUI 的**鼻祖级项目**(YoutubeDL-Material 明确致谢它),但已被 yt-dlp 生态取代。**借鉴**:把解析核心做成独立库,Web 只是壳。

---

## 六、NickvisionApps/Parabolic(桌面形态,非 Web 服务)

| 项目 | 信息 |
|---|---|
| 仓库 | https://github.com/NickvisionApps/Parabolic |
| Star | **7,156** 实测;License **MIT**;主语言 C# |
| 活跃度 | 实测 pushed_at = **2026-06-29**,活跃;创建于 2021-12;Flathub 分发 |

- **架构**(实测 README):.NET 10 桌面应用——GNOME 版 **GTK4/libadwaita**,Windows 版 **WinUI3/WindowsAppSDK**;**yt-dlp 前端**,支持 mp4/webm/mp3/opus/flac/wav、并发下载、元数据与字幕下载;配套 Firefox/Chrome 浏览器扩展(右键直接发送链接到桌面应用)。
- 与本题关系:**不是 Web/API 形态**,但作为「粘贴链接 → 解析 → 下载」的 UX 参照和 yt-dlp 桌面包装标杆有参考价值;aria2 集成等说法未在本仓库 README 中核实。

---

## 七、其他值得关注的项目(简表)

| 项目 | 形态与架构(实测 README/第三方页) | 备注 |
|---|---|---|
| Tzahi12345/YoutubeDL-Material | **Angular 15 前端 + Node.js 后端**,包装 youtube-dl/yt-dlp;数据默认 JSON 文件、可选 **MongoDB**;提供带 apiKey 的 Public API(Stoplight 文档)、iOS 快捷指令;MIT;stars **3,136**(第三方 repoportal 实测);致谢 AllTube | 功能齐全(订阅/播放列表/库),近年维护放缓(最新 release v4.3.1;仓库最近推送时间未核实) |
| lunae-f/dler | **FastAPI + Celery + Redis + yt-dlp**,原生 HTML/JS 前端,Docker Compose,MIT(实测 README,日文) | 麻雀虽小,任务状态(处理中/成功/失败)与 Celery 队列结构清晰,是「最小可用」参照;stars 未核实 |
| renbkna/yt-dlp-ui | 基于 yt-dlp 的 Web 下载界面(搜索结果,未深抓) | 同类长尾项目;未核实 |
| qokelate/yt-dlp-webui | yt-dlp-web-ui 的分支/变体(DeepWiki 有系统设计文档,未深抓) | 未核实 |

---

## 八、总结:通用架构模式

无论自研解析还是包装 yt-dlp,这类产品的链路收敛为同一张骨架:

```
浏览器表单(粘贴链接,可能带清晰度/格式选项)
        │ POST /parse (JSON, 入口 URL 白名单校验)
        ▼
后端任务层 ──► 同步直回 / 202+task_id 轮询 / SSE / webhook 回调
        │
        ▼
解析引擎 ──► A. 自研解析器(cobalt、Douyin_API: 直连平台 API,选无水印流)
          ──► B. 包装 yt-dlp(metube、yt-dlp-web-ui、Parabolic、alltube、dler、YDL-Material)
        │
        ▼
ffmpeg 转封装/合并(m3u8→mp4)、音频提取、缩略图/字幕
        │
        ▼
回传:服务端直链流式下载 / 落盘后静态文件路由 / 302 平台直链
        │
        ▼
运营配套:Docker 部署、限流(IP/Key 双桶)、验证码/鉴权、cookie 池与反风控
```

规律:

1. **自研解析器**(cobalt、Douyin_TikTok_Download_API)换来的是质量(无水印、8K、HDR、干净元数据)与速度,代价是每个平台都要维护逆向/签名逻辑,平台一改就坏——Douyin_API 的 v4→v5 重写就是被「静默失效」逼出来的。
2. **包装 yt-dlp**(metube、yt-dlp-web-ui、Parabolic、dler、YDL-Material、alltube)换来的是上百个站点的长尾覆盖与零逆向成本,代价是依赖上游社区、无水印/清晰度受制于 yt-dlp 提取器、性能与可控性弱。
3. **任务形态三档**:metube/Parabolic 的「进程内队列 + 少量并发」→ yt-dlp-web-ui/dler 的「SQLite/Celery+Redis 队列」→ Douyin_API v5 的「完整异步任务系统(202+task_id+SSE+webhook+归档)」。公开运营的产品必须走到第三档,且必须配备:cookie/身份池自愈、令牌桶限流、熔断、入口 URL 白名单、SSRF 防护、API key 分权。
4. **无水印只有两种真实做法**:①选平台官方发布的无水印流(抖音/TikTok 平台的干净 CDN 地址,cobalt 与 Douyin_API 都是这个口径);②下载后像素级处理(水印裁剪/模糊,几乎无人做、易被告)。**没有任何项目是"从零合成无水印视频"的。**

## 九、cobalt vs Douyin_TikTok_Download_API:设计思路核心差异

| 维度 | cobalt(imputnet) | Douyin_TikTok_Download_API(Evil0ctal) |
|---|---|---|
| 解析路线 | **自研解析器**,每平台一个模块,无 yt-dlp | **自研解析器 + 逆向签名**(a_bogus 等 4 套纯 Python + 浏览器回退),无 yt-dlp |
| 平台取向 | 海外为主 20+ 站;国内仅 B 站;**无抖音** | **抖音 + TikTok 双平台深耕**;v5 暂无 B 站/快手 |
| 任务模型 | **同步代理**:POST → tunnel/redirect 流式,不落盘不排队 | **异步任务系统**:202+task_id、worker、队列、SSE、webhook、归档 |
| 存储 | **零持久化**(内存 tunnel 90s TTL,可选 Redis 缓存) | **PostgreSQL+TimescaleDB 全量归档** + Redis 缓存/队列 + 磁盘媒体库 |
| 反风控 | cookie 注入、YouTube poToken 服务、FREEBIND 随机 IPv6 | **自愈身份池**(无头浏览器铸造游客身份)+ 健康分层 + 令牌桶 + 熔断 |
| 防滥用 | Turnstile + JWT + 分级 API key + 三级限流(IP/会话/tunnel) | scope 化 API key + 角色 + 每 key 分钟限流 + 队列上限 + 请求合并 |
| 产品形态 | 极简「粘贴→拿文件」工具,官网运营 | 数据中台式 API:解析/归档/下载/订阅/MCP/CLI |
| License | API AGPL-3.0;前端 CC-BY-NC-SA(禁商用) | Apache-2.0(可商用) |

**一句话对比**:cobalt 是「无状态的优雅代理」——把一切状态交给内存和浏览器,赢在简单、隐私与防滥用;Douyin_API 是「有状态的生产系统」——把身份、队列、归档、观测做成中台,赢在对国内平台风控的工程化对抗与 API 完备性。**对我们的产品**:海外平台可借鉴 cobalt 的解析/状态机/防滥用,国内平台(抖音/快手/B 站)必须走 Douyin_API 的签名+身份池路线,而任务层(202+task_id+SSE+归档)与限流体系(Douyin_API v5 全套)是公开网站商业化运营的必需品。
