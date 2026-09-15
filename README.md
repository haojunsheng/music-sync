# music-sync

个人音乐跨平台同步工具：从多个音源抓取无损音频，校验时长、写入歌词与元数据标签，并直传到网易云音乐个人云盘。

核心思路是**先拿到权威元数据，再去找音频**——用官方元数据（歌名/歌手/专辑/时长/封面）做锚点，避免下到翻唱、DJ 版、现场版这类同名干扰项。

```
官方元数据锚点 → 遍历音源搜索 → 音质筛选 → 下载+时长校验 → 歌词+标签写入 → 网易云云盘直传
```

## 功能特性

- **元数据锚点**：Apple Music（可选，配 token 后优先）→ QQ 音乐 → iTunes → MusicBrainz → 网易云，逐级回退，拿不到就降级为原始输入
- **多音源聚合**：QQ / 咪咕 / 酷我 / 网易云 / 酷狗 / B站 / YouTube / 1music 八个音源，按配置顺序遍历
- **无损优先策略**：命中无损立即停止检索；低于可接受档位（默认 `flac/ape/320k`）的候选直接丢弃
- **黑名单过滤**：默认屏蔽 DJ / 慢摇 / remix / 翻唱 / live / 伴奏 / 加速减速变调等干扰版本
- **时长校验**：下载后实测音频时长，与基准时长偏差超过容差（默认 10s）则丢弃文件
- **标签写入 + 回读校验**：写入标题/歌手/专辑/歌词/封面后重新读取验证，不信任"写入成功"的返回值
- **网易云云盘直传**：按官方 5 步流程走完 check → NOS 凭证 → 二进制流 → 资源登记 → 发布，非会员也能同步自有版权音频
- **批量同步**：支持 CSV 歌单和「某歌手热门歌曲」两种批量入口，逐首隔离失败
- **395 个单元测试**：全程离线打桩，不触网、不读写用户真实配置

## 环境要求

- Python 3.9+（开发与测试环境实测 3.12.13；代码未使用 3.10+ 专属语法）
- 可选：`yt-dlp`（仅 YouTube 音源需要）

## 安装

```bash
git clone git@github.com:haojunsheng/music-sync.git
cd music-sync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 快速开始

```bash
# 1. 扫码登录网易云（云盘直传与歌词获取都需要登录态）
.venv/bin/python -m music_sync login

# 2. 同步单曲
.venv/bin/python -m music_sync sync "断桥残雪" --artist "许嵩"

# 3. 只预览匹配结果，不下载不上传
.venv/bin/python -m music_sync sync "断桥残雪" --artist "许嵩" --dry-run

# 4. 批量同步某歌手的热门歌曲
.venv/bin/python -m music_sync artist "许嵩" --limit 20

# 5. 批量同步 CSV 歌单（格式：title,artist[,album]）
.venv/bin/python -m music_sync batch songs.csv
```

下载产物默认落在 `~/Music/music-sync/<首位歌手>/<歌名>.<ext>`，合作曲目按首位歌手归档（`许嵩/何曼婷` → `许嵩/`），但写入文件的 `ARTIST` 标签保留完整歌手串。

## 命令参考

| 命令 | 说明 |
| --- | --- |
| `login` | 扫码登录网易云音乐并保存 Cookie |
| `sync <title> [-a 歌手] [--album 专辑]` | 同步单首歌曲 |
| `batch <csv_file>` | 按 CSV 批量同步（`title,artist[,album]`） |
| `artist <name> [--limit N]` | 批量同步某歌手的热门歌曲（默认 50 首） |
| `config [选项]` | 查看或修改配置，不带选项则打印当前配置表 |

通用选项：

- `--dry-run`：只预览命中候选，不下载、不上传
- `--no-upload`：只下载打标，不同步到网易云云盘
- `--force`：忽略本地已有文件，强制重新下载（默认会复用本地文件）
- `--flac-only`：仅 `sync` 支持，强制只接受无损音源

## 工作流程

实际输出里的阶段编号沿用代码里的注释（M3 已并入 M2 的筛选逻辑，故跳号）：

| 阶段 | 做什么 | 失败处理 |
| --- | --- | --- |
| M1 | 取基准元数据（歌名/歌手/专辑/时长/封面） | 逐级回退，最终用原始输入兜底 |
| M2 | 按配置顺序遍历音源，筛音质、去黑名单、选最优候选 | 命中无损即停止检索；无候选则报错并提示配置凭证 |
| M4 | 下载到 `<首位歌手>/<歌名>.<ext>`，实测时长校验；**本地已有同名文件且校验通过时直接复用，不重复下载** | 校验不过直接删文件返回失败 |
| M5 | 取歌词 + 写入标签 + 回读校验 | 标签校验失败视为失败 |
| M6 | 网易云云盘查重，未命中则直传 | 云盘失败**不影响**本地文件，任务整体仍判成功 |

## 重复执行（幂等性）

重复跑同一首歌是安全的，不会做无谓的工作：

- **本地已有同名文件且时长校验通过** → 跳过下载，直接复用（`sync` 只花几秒而不是重下几十 MB）
  - 本地文件校验不过（下残/下错）→ 自动重新下载
  - 想强制重下：`--force`（`sync` / `batch` / `artist` 都支持）
- **本地文件复用后仍会走 M5 打标与 M6 云盘同步** —— 所以上次云盘上传失败的话，再跑一次就能补上上传，不必重新下载
- **云盘已有该曲目** → 跳过上传
- 下载先落到 `<文件>.part`，完整拿到后才原子替换目标文件；下载中断不会把已有的好文件截断

## 基准元数据源

M1 按优先级向下列源要「基准元数据」（歌名/歌手/专辑/时长/封面），命中即停：

```
Apple Music → QQ 音乐 → iTunes → MusicBrainz → 网易云 → Fallback(原始输入)
```

| 源 | 需要凭证 | 特点 |
| --- | --- | --- |
| Apple Music | `apple_music_token` | 毫秒级时长、ISRC、精确发行日期；封面最长边可达 3000px（其他源只给 300~600px）。**未配 token 直接跳过** |
| QQ 音乐 | 无需（VIP 直链才要 Cookie） | 中文曲库覆盖最全，发行信息最准 |
| iTunes | 无需 | Apple 公开接口，自动试 CN/US/JP 多区 |
| MusicBrainz | 无需 | 缺封面时用网易云补齐 |
| 网易云 | 无需 | 兜底 |

### Apple Music 只能做元数据源，不能做音源

Apple Music 的完整音轨受 **FairPlay DRM** 保护，网页播放器的 Bearer token 换不到可解密的音频流——官方 `previews` 只有 30 秒片段，歌词接口对该 token 也返回 404。本项目不做 DRM 绕过，所以 Apple Music 只参与 M1（元数据 + 高清封面），**音频仍然从 `sources/` 下的普通音源下载**。

```bash
# 配置（token 是网页播放器那种 Bearer JWT，从 music.apple.com 的请求头里取）
.venv/bin/python -m music_sync config --apple-music-token "<Apple Music Bearer token>"
.venv/bin/python -m music_sync config --apple-music-storefront cn   # 区域，默认 cn
.venv/bin/python -m music_sync config --apple-music-priority false  # 降级到 QQ 之后
```

> token 是短期凭证（一般几个月过期）。过期后 M1 会打印提示并**自动回退**到 QQ 音乐，不会让整条流水线失败。

**开关 `apple_music_priority` 怎么选：**

- `true`（默认）—— Apple Music 命中即用它的歌名/歌手/专辑/发行年。
- `false` —— 退到 QQ 音乐之后、iTunes 之前。中文曲目优先保 QQ 的发行信息，非中文曲目仍由 Apple 兜住。**升级既有曲库时建议先关掉**，避免同一首歌因源头不同被归到另一个歌手目录下。

### 命名归一化（Apple 数据的两处「水土不服」）

Apple 的元数据在中文曲目上有两个和 QQ 不一致的习惯，直接沿用会让本地曲库出现重复文件，所以这里做了收敛（只在「去掉修饰后与用户查询完全一致」时才动手，不会误伤）：

- **曲名尾部括注**：Apple 把影视出处写进曲名，如 `后会无期 (《诡案》网络剧插曲)`；归一化为用户查询的 `后会无期`，避免上一轮下的 `后会无期.flac` 这轮复用不上、白下一遍。
- **合作歌手排序**：Apple 给 `汪苏泷 & 徐良`，QQ 给 `徐良/汪苏泷`。归档目录取首位歌手，若不处理，用「徐良」查的歌会被归进 `汪苏泷/`，同一首歌在曲库里分成两份。归一化会把**查询歌手提到首位**（不增不减歌手）。

## 音源与音质策略

音源遍历顺序取自配置项 `sources`，默认：

```
qq → migu → kuwo → netease → kugou → bilibili → youtube → 1music
```

音质档位取自 `quality_priority`（默认 `flac,ape,320k`，按优先级从高到低）。**不在这份列表里的档位一律拒绝**——不会静默降级到 128k。

- 命中无损（`flac`/`ape`）→ 立即停止检索其余音源
- 只找到有损 → 暂存并继续找无损
- `--flac-only` 或 `allow_lossy_fallback=false` → 只保留无损档位

各音源现状（实测）：

| 音源 | 状态 |
| --- | --- |
| QQ 音乐 | 可用，但 VIP/版权曲目需配置会员 Cookie 才返回直链 |
| 网易云 | 可用，无损直链走 eapi 通道，需登录态；VIP 专享曲目同样取不到直链 |
| 酷我 | 可用，但不少曲目搜得到、拿不到直链 |
| 酷狗 | 可用；付费/VIP 曲目取不到直链（playInfo 老接口已失效） |
| B站 / YouTube | 可用（YouTube 需 `yt-dlp`） |
| 咪咕 | 接口返回非 JSON 页面，**已失效，待更换新接口** |
| 1music | 需配置 `token_1music`，未配置时自动跳过 |

## 配置

配置文件：`~/.config/music-sync/config.json`（首次运行自动生成）
登录凭证：`~/.config/music-sync/netease_cookie.json`

```bash
# 常用配置示例
.venv/bin/python -m music_sync config --qq-cookie "<QQ音乐会员 Cookie>"
.venv/bin/python -m music_sync config --quality-priority "flac,320k"
.venv/bin/python -m music_sync config --allow-lossy false      # 只收无损
.venv/bin/python -m music_sync config --tolerance-seconds 5     # 收紧时长容差
.venv/bin/python -m music_sync config --bilibili-cookie "<B站 Cookie>"
.venv/bin/python -m music_sync config --apple-music-token "<Apple Music Bearer token>"
.venv/bin/python -m music_sync config --apple-music-storefront cn
.venv/bin/python -m music_sync config --apple-music-priority false
.venv/bin/python -m music_sync config                          # 打印当前配置
```

主要配置项：`tolerance_seconds`、`quality_priority`、`allow_lossy_fallback`、`sources`、`download_dir`、`blacklist_keywords`、`use_system_proxy`，以及各音源的 Cookie / Token（含 `apple_music_token` / `apple_music_storefront` / `apple_music_priority`）。

> `*_cookie.json`、`.env`、音频产物已在 `.gitignore` 中排除，**切勿把凭证提交进仓库**。

## 网易云云盘直传

云盘上传是一条 5 步链路，**缺任何一步都不会出现在「我的云盘」里**：

| 步骤 | 接口 | 作用 |
| --- | --- | --- |
| 1 | `/api/cloud/upload/check` | 用 md5 换 `needUpload` + `songId` |
| 2 | `/api/nos/token/alloc` | 换 NOS `token` / `objectKey` / `resourceId` |
| 3 | `<LBS 下发域名>/<bucket>/<objectKey>` | 二进制流直传（`needUpload=false` 时跳过） |
| 4 | `/api/upload/cloud/info/v2` | 登记资源元信息，拿新的 `songId` |
| 5 | `/api/cloud/pub/v2` | 发布到个人云盘 |

实现要点（都是踩过坑的地方）：

- 走 **eapi** 通道（`interface.music.163.com/eapi` + AES-128-ECB），weapi 已被服务端下线，会返回 `200 + 空 body`
- `/api/cloud/upload/check` 用的是**扁平参数** `{bitrate, ext, length, md5, songId, version}`，早期那种 `{uploadType, songs:[...]}` 数组写法会回 `400 参数错误`
- `docId` 在"云端已有同 md5"时是 `-1`，**不能当 resourceId 用**；真正的 id 在 `result.resourceId`
- NOS 上传节点由 `wanproxy.127.net/lbs` 动态下发，写死域名不行；`objectKey` 里的 `/` 必须转义成 `%2F`
- `song` / `artist` / `album` 三个字段不能包含 `.` 和 `/`，否则登记直接失败
- 接口 400 响应常常**只有 `code` 没有 `message`**，所以错误提示里必须带上 code，否则排查时只剩"未知错误"
- `uploadStatus: 9` 是服务端瞬时限流态（响应里有 `waitTime` / `nextUploadTime`），短时间内重复上传同一 md5 会撞上，**等一会重试即可，不是参数错误**

## 项目结构

```
music_sync/
├── cli.py              # 命令行入口与子命令
├── pipeline.py         # 主流程编排（M1~M6）+ 批量/歌手同步
├── config.py           # 配置读写与默认值
├── metadata.py         # 基准元数据获取（Apple Music/QQ/iTunes/MusicBrainz/网易云）
├── artist.py           # 歌手热门歌曲列表（QQ 优先，网易云回退）
├── netease.py          # 网易云客户端：登录、云盘查重、5 步直传
├── netease_crypto.py   # weapi / eapi 加密实现
├── lyrics.py           # 歌词获取
├── tagger.py           # 音频标签写入与回读校验
├── validator.py        # 时长/艺人匹配校验
├── http.py             # 统一 session（重试、超时、代理）
└── sources/            # 八个音源适配器，统一 TrackCandidate 结构
tests/                  # 395 个单元测试
```

新增音源只需实现 `BaseSource.search_and_resolve()` 并在 `sources/__init__.py` 的 `SOURCE_REGISTRY` 注册。

## 测试

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 395 个用例
```

测试有两条硬约束（见 `tests/conftest.py`）：

1. **全程离线**——所有 HTTP 调用由 `StubSession` 打桩，不访问真实网络
2. **不污染本机**——配置与凭证文件路径被重定向到临时目录

涉及云盘上传的用例会**解密 eapi 的 `params`**，直接断言发往线上的真实参数，避免"本地看着对、线上被拒"。

> 请从项目根目录执行 `pytest`：`pytest.ini` 把 `--basetemp` 固定到项目内的 `.pytest_tmp`（受限环境下对系统临时目录建目录会失败）。

## 免责声明

仅供个人学习与自用。请遵守各音乐平台的版权与用户协议，不要用于分发或商业用途。

Apple Music 集成**只读取目录元数据**（歌名/歌手/专辑/时长/封面），不下载、不解密、不绕过其 DRM；token 请自行获取并只保存在本机 `~/.config/music-sync/config.json`（已在 `.gitignore` 覆盖范围之外，**切勿提交进仓库**）。
