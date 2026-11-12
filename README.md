# 留影 · Liuying

Apple 风格的分享链接视频下载网站。当前为 **0.1 本地可运行版**，不是只有点击动画的原型。

白、浅灰、石墨黑与经典蓝；桌面和手机自适应。包含下载页、任务中心、平台能力页。

## 立即运行

需要 Node.js 22.12+ 和 [uv](https://docs.astral.sh/uv/)。Python 3.12 由 uv 安装，媒体校验使用系统 FFmpeg 或依赖内附的 FFmpeg。

```sh
./start.sh
```

浏览器打开 **http://127.0.0.1:8000**。首次运行会安装依赖并编译前端；不需要 Docker、外部 API Key 或数据库服务。停止时按 Ctrl+C。

点击「试用公开样片」即可走真实的解析、准备文件、保存到设备流程。样片为 [W3C 托管的 Sintel 预告片](https://media.w3.org/2010/05/sintel/trailer.mp4)，不会伪装成无水印验证样本。

如需只启动已编译版本：

```sh
uv run --frozen uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

开发前端时，在另一终端执行 `npm --prefix web run dev`，打开 http://127.0.0.1:5173 。Vite 将 `/api` 请求转发给 8000 端口。

## 本版真实能力

- 从完整分享文案中提取单条链接，识别来源并调用对应适配器。
- 展示真实返回的标题、画质、文件大小估计和水印状态；未知信息不会补造。
- 下载前重新解析源地址；分轨音视频本地无损合并；先检查文件再允许保存。
- SQLite 持久化任务；事件流推送，断线后轮询；刷新后可从任务中心恢复。
- 取消、重试、到期重建；下载进度来自实际接收字节。
- 文件下载使用当前会话绑定的 5 分钟签名票据，支持 HTTP Range。
- 默认单文件 8 GiB、单条视频最长 4 小时(单个下载任务墙钟 4 小时)、2 个处理进程、24 个活跃任务、临时文件保留 1 小时。
- 下载文件在浏览器下载目录中保存；网页无法自行确认用户设备最终写盘，只提示「已发起下载」。

### 平台状态：代码接入 ≠ 现网可用性承诺

| 来源 | 接入方式 | 当前验证范围 |
| --- | --- | --- |
| 公开视频直链 | HTTP(S) + 本地媒体校验 | Sintel 样片真实解析、下载、浏览器保存通过 |
| 抖音 | 本机 Chrome 铸造访客身份 + 原生 a_bogus/secsdk 签名(免登录);配置 `LIUYING_DTK_URL` 后优先走专用服务 | 真实分享文案/短链解析、1080P 无水印下载、浏览器保存通过 |
| TikTok | yt-dlp 使用 Chrome UA，媒体请求沿用当前任务的访客会话。可选 Evil0ctal v5 独立服务 | 两条此前失败的公开视频在公网 worker 上用新版代码完整下载通过 |
| 快手 | 游客 `feedbyid` 接口与公开移动分享页 | 真实长链的游客接口版本和移动网页版本均通过文件校验，移动网页可能提供独立的播放版本 |
| 小红书 | 桌面与移动 SSR，保留分享 token 并核对作品 ID | 真实公开样本在公网 worker 上用新版代码完整下载通过。部分链接仍受权限或签名时效限制 |
| B站 | yt-dlp + 平台返回的标准 HTTPS 备用 CDN，音视频分轨合并 | BV1uzhX6LEVa 公网解析、1080P 带音频下载及 Range 验证通过（2026-09）；其他作品仍受平台权限与接口限制 |
| YouTube / Instagram / X | yt-dlp，过滤可用直连格式 | YouTube 短链解析 + 240P 下载验证通过；其余待验收 |
| 西瓜 / 视频号 | 未接入 | 暂未开放 |

> 抖音解析依赖本机 Chrome/Chromium 铸造访客身份(`api/douyin_mint.py`,身份缓存于 `.data/douyin_identity.json`,约 20 分钟复用一次);服务端机器没有浏览器时请配置 `LIUYING_DTK_URL` 使用专用解析服务。

“无水印”指尽可能取得平台提供的未加水印视频源；并非对任何视频做像素修复。水印分为「平台无水印源 / 带水印 / 未知」，原作者已有文字或标志可能保留。不会把改名、压缩或下载成功视为去水印成功。

当前不支持：DRM 解密、付费权限绕过、验证码自动处理、直播、主页批量、图集、HLS 分片、AI 画面水印修复。私有内容和平台拒绝访问时返回具体失败信息。仅保存你有权使用的内容。

## 配置

复制 `.env.example` 为 `.env` 并按需修改；不配置也能运行。配置在服务启动时读取，修改后重启。

| 配置 | 用途 |
| --- | --- |
| `LIUYING_DATA_DIR` | 任务数据库、会话签名密钥、临时文件目录，默认 `.data` |
| `LIUYING_MAX_BYTES` / `LIUYING_MAX_DURATION` / `LIUYING_DOWNLOAD_TIMEOUT` | 单文件大小上限(默认 8 GiB)、单条视频时长上限(默认 4 小时)、单个下载任务的墙钟超时(默认 4 小时)。长视频可自行调大；超限视频会在解析、下载、合并后的媒体校验阶段被明确拒绝 |
| `LIUYING_ARTIFACT_TTL` | 临时文件存活秒数，默认 3600 |
| `LIUYING_DTK_URL` / `LIUYING_DTK_API_KEY` | 你自行部署的 Evil0ctal v5 基础 URL 和密钥；不自动安装或公开该服务 |
| `LIUYING_DOUYIN_PROXY` | 可选的抖音专用代理，供访客浏览器、作品接口、封面及视频下载共用；留空直连。地址必须能从 worker 内访问。Mac + Colima 可使用宿主机代理网关地址；部署到其他服务器时须重新配置，勿照搬本机地址 |
| `LIUYING_COOKIE_FILE` | 实例管理员自行提供的 Netscape cookie 文件。本地或私有实例使用。Docker Compose 下请填写容器内可访问的文件路径 |
| `LIUYING_ACCESS_PASSWORD` | 访问密码：非空时首页与全部接口(健康检查除外)要求先输入该密码，登录失败按 IP 限流；留空则无密码，仅限本机使用 |
| `LIUYING_SECURE_COOKIE` | 通过 HTTPS(如 Cloudflare Tunnel / 反向代理)访问时设为 `true` |
| `LIUYING_FORWARDED_ALLOW_IPS` | Docker Compose 下 API 信任的反向代理来源地址，默认 `127.0.0.1,::1`。宿主机反代经 Docker 网桥访问时填实际网桥网关地址，以识别 HTTPS |
| `LIUYING_ALLOWED_HOSTS` | 允许的 Host，JSON 数组；公网发布时需加入自己的域名 |
| `LIUYING_PROXY` | 海外平台（YouTube / TikTok / Instagram / X）解析、封面和视频下载的出口代理 `http(s)://主机:端口`。留空时读取进程的 `https_proxy` / `http_proxy`，皆空则直连。Docker Compose 下代理地址须能从 worker 容器访问。抖音使用独立的 `LIUYING_DOUYIN_PROXY`，其余国内平台直连 |
| `LIUYING_DATABASE_URL` / `LIUYING_QUEUE_MODE` | 切换 PostgreSQL / Celery |

平台签名与 Cookie 不交给浏览器，临时 CDN 地址也不直接公开。配置了个人登录态的实例不要开放成匿名公共服务。当前提供共享访问密码，没有多用户账号系统或用户独立凭据仓库。

媒体记录中的封面及临时 CDN 源信息保留 24 小时；临时视频按 TTL 清理。当前任务历史（包括原始分享链接）保留在本地数据库，不提供一键删除入口。浏览器会话 cookie 有效期 30 天；清除 cookie 后无法找回该会话记录。文件到期只影响服务器临时文件，不删除已保存到设备的副本。默认启动命令关闭访问日志，避免下载票据进入 URL 日志。

## 公网发布(Cloudflare Tunnel)

> ⚠️ 法律与合规:此类站点公开运营存在版权与平台条款风险(开源界已有同类项目收到律师函后关停的先例)。仅建议用于**个人学习研究**;不要对外提供商业服务,不要绕过 DRM 或付费权限,只保存你有权使用的内容。

域名由 Cloudflare Tunnel 指向 Debian 服务器。Docker Compose 在 `/opt/liuying` 运行 API、worker、PostgreSQL 与 Redis；`cloudflared-liuying.service` 通过 systemd 常驻，并转发到本机 `127.0.0.1:18000`。Tunnel 凭据位于 `/etc/cloudflared/`，访问密码与数据库密码保存在 `/opt/liuying/.env`（权限 600）。

检查与重启：

```sh
cd /opt/liuying
docker compose ps
docker compose up -d --build
systemctl status cloudflared-liuying
```

打开 [留影公网实例](https://wanxingchen666.xyz)。配置了访问密码的实例可用默认模式验收，公开访问的实例使用 `--anonymous`。

```sh
.venv/bin/python scripts/smoke_public.py
.venv/bin/python scripts/smoke_public.py --anonymous --download
```

脚本检查 HTTPS、会话 Cookie、接口和前端资源。`--download` 额外创建公开样片任务，验证文件下载、Range 和跨会话隔离。密码模式使用本地 `.env` 中的访问密码，脚本输出只包含检查结果。

下载出口流量由 Debian 服务器提供。修改访问密码后执行 `docker compose up -d` 使配置生效；旧会话会失效。

## 验证

```sh
uv run pytest -q
uv run ruff check api tests scripts
npm --prefix web run build
```

未启用访问密码的本地开发实例，可额外执行真实网络测试；公网实例使用上面的 `smoke_public.py`：

```sh
uv run python scripts/smoke_http.py
npm --prefix web run test:e2e
```

浏览器测试需要本机 Chrome；可用 `PLAYWRIGHT_CHANNEL` 指定另一已安装的 Chromium 系浏览器。截图与测试下载保存在 `test-results/`，不纳入版本控制。接口 smoke 不会保存第二份测试视频到工作区，只下载到内存比对。

公开样片真实下载 4,372,373 字节，Range 返回 206，媒体和文件受会话隔离保护。桌面与手机验收范围见 [验收记录](./design/实现与验收记录.md)。各平台真实样本的验收范围见上文的平台表。

## 可选 Docker 拓扑

```sh
docker compose up --build
```

包括 API、Celery worker、PostgreSQL 和 Redis，文件目录共享。站点通过宿主机的 `127.0.0.1:18000` 访问。数据库和 Redis 只在 Compose 网络内可访问。

Compose 默认密码仅适用于本机开发。对外服务前应设置独立密码、HTTPS、认证、配额、反向代理请求体限额、备份和平台授权策略。当前 Python 网络地址检查不是操作系统级隔离；公开部署还需要独立出站网关、内网/元数据网段防火墙规则以及受限 worker 容器。禁止直接把个人 Cookie 实例映射到公网。

## 工程结构

```text
api/                 FastAPI、持久化任务、独立解析/下载进程
web/                 React + TypeScript + Vite，真实 API 驱动
tests/               安全、状态机、下载票据、适配器合同测试
scripts/smoke_http.py 实际网络链路验证
design/              实现与验收记录
```

Evil0ctal 使用独立服务协议适配，没有把其仓库源码复制进本应用。实际依赖版本固定在 `uv.lock` 和 `web/package-lock.json`。发布或商用前应单独检查所分发依赖及 FFmpeg 构建的许可证要求。
