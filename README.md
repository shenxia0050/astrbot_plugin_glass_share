# 希望解析器

> [!NOTE]
> **二次修改版声明**：本项目基于 [xiaoxi2760/astrbot_plugin_denia_share](https://github.com/xiaoxi2760/astrbot_plugin_denia_share) 修改，并保留原项目的版权及 MIT 许可声明。本版本由 `shenxia0050` 在上游项目基础上修改和维护。
>
> 为避免与上游项目重名、干扰原插件的搜索与使用，本仓库及插件已更名为 **`astrbot_plugin_glass_share`**（显示名「希望解析器 · Glass」）；上游署名、许可证与致谢保持不变。主要新增/修改包括：
>
> * 新增 `glass` 玻璃卡片布局（浅色粉蓝渐变 + 内嵌圆角封面 + 白色统计面板，全平台生效，并作为本版默认布局）；
> * 修复长简介溢出简介框；
> * 玻璃背景改为三段式渐变并消除光晕裁切硬边；
> * 为 B 站音视频合并增加 `-movflags +faststart`（moov 前置，修复部分客户端视频卡片外显竖屏占位 / 时长 00:01）；
> * B 站 DASH 编码优先级调整为 AVC > AV1 > HEVC（部分 QQ 客户端解不了 AV1 封面，这是卡片外显异常的另一半根因）；
> * 修复 Twitter 解析：第三方 API（vxtwitter / fxtwitter）改用专用 UA（浏览器 UA 会被 Cloudflare 拦 403），并修复 `x.com` 链接主机名改写错误导致的必然超时；
> * 新增可选的「按域名定向代理」：仅对 Twitter 媒体 CDN 走兜底代理（`LOCAL_PROXY_FALLBACK`，默认关闭、留空即不启用），其余平台照旧直连；
> * 同步增加 WebUI 与相关配置项。
>
> 本项目中部分代码来自其他开源项目，具体版权及许可证如下：
>
> * [xiaoxi2760/astrbot_plugin_denia_share](https://github.com/xiaoxi2760/astrbot_plugin_denia_share) — MIT
> * [iris1598/astrbot_plugin_rika_share](https://github.com/iris1598/astrbot_plugin_rika_share) — MIT
> * [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2) — Apache-2.0
>
> 第三方项目的原版权声明、许可证文本及相关归属信息，以仓库中的 [LICENSE](LICENSE)、[LICENSES/](LICENSES) 及对应源文件头部声明为准，汇总见 [LICENSES/THIRD-PARTY-NOTICES.md](LICENSES/THIRD-PARTY-NOTICES.md)。
>
> 本项目自身新增或修改的代码，在不影响上述第三方许可证义务的前提下，同样采用 MIT 许可证。

支持多平台链接解析，并自带一个网页界面（WebUI）：把分享链接解析成结构化内容，渲染成分享卡片发出来。

支持 **B站 / 抖音 / 快手 / 微博 / 小红书 / Twitter(X) / AcFun / NGA / GitHub / Pixiv / Steam**
十一个平台，另有网页截图（`/shot`）与 Pixiv 搜索（`/pixiv`）。不够用还可以自己加平台，
见[自定义解析器](#自定义解析器)。

## 各平台解析什么

| 平台 | 内容 |
| --- | --- |
| B站 | 视频 / 动态 / 直播 / 专栏 / 收藏夹 |
| 抖音、快手 | 视频 / 图集 |
| 微博 | 正文 / 视频 / 长文 |
| 小红书 | 笔记（图文 / 视频），图片与封面统一改写为无水印原图 |
| Twitter / X | 推文（图片 / 视频） |
| AcFun | 视频 |
| NGA | 帖子 |
| GitHub | 仓库卡片：星标 / 分支 / 未关闭 issue / 主语言 / 许可 / topics / 最近提交 |
| Pixiv | 作品；`xRestrict != 0` 的内容**一律拦截**，不提供开关 |
| Steam | 商店页：名称 / 简介 / 开发商 / 发行日期 / 类型 / 国区价格 / 折扣 |

结果会渲染成分享卡片（**4 种布局 × 深浅双主题**），也可以在配置里关掉、回退纯文本。
另外支持 QQ 小程序分享卡片（`Json` 消息段）里的链接提取，以及 OneBot 合并转发发送。

## 安装

1. 把 `astrbot_plugin_denia_share` 放进 AstrBot 的 `data/plugins/` 目录
2. 安装依赖：`pip install -r requirements.txt`
3. **装 ffmpeg**：视频处理要用它（B站高清的音视频合并、视频没有现成封面时抽帧）
4. 重启 AstrBot，在插件管理里启用

> 自带的网页界面需要 AstrBot **>= 4.25.3**。更老的版本插件照常工作，只是没有这个页面。

## 用法

**群里直接发链接就会被解析**，不需要命令。命令只有这几条：

| 命令 | 作用 | 权限 |
| --- | --- | --- |
| `/shot <网址>` | 网页截图 | 全部 |
| `/pixiv <关键词>` | Pixiv 搜索，最多 6 张，强制过滤非全年龄 | 全部 |
| `/bili_login` | B站扫码登录（想下 1080P 及以上才需要） | 管理员 |
| `/bili_check` | 检查 B站 Cookie 是否有效 | 全部 |
| `/denia_status` | 查看插件运行状态 | 管理员 |
| `/denia_clear` | 立即清空解析缓存 | 管理员 |

## 网页界面

Dashboard 侧边栏「插件 WebUI → 希望解析器」，分五个标签：

| 标签 | 用途 |
| --- | --- |
| **总览** | 运行状态、B站扫码登录、平台一键开关（含自定义解析器的启停） |
| **解析** | 手动粘贴链接预览卡片（可临时换主题 / 布局），网页截图小工具，自定义解析器管理 |
| **缓存** | 解析记录的搜索 / 筛选 / 分页 / 预览 / 删除，以及缓存清理 |
| **外观** | 上半改网页观感，下半是卡片设计器（右侧实时预览，边调边看） |
| **配置** | 全部配置项，按大类分组、可折叠、可搜索 |

配置改完**保存即生效**，不需要重载插件。

**两套「外观」是刻意分开的**：界面自定义只改你自己看到的这个网页，卡片设计器改的才是
真正发出去的卡片。

## 配置

配置项都在网页界面的「配置」页里维护，分 9 组、带说明、可搜索，不用手改 json。
最常动的几项：

| 项 | 默认 | 说明 |
| --- | --- | --- |
| `DISABLED_PLATFORMS` | 空 | 关掉不想解析的平台，逗号分隔 |
| `VIDEO_DURATION_MAXIMUM` / `VIDEO_SIZE_MAXIMUM_MB` | 480 秒 / 100 MB | 超限不下载视频，卡片照发 |
| `SEND_ERROR_MESSAGES` | 关 | 解析失败要不要在群里回一句；关了更安静 |
| `BILI_CK` | 空 | 建议用 `/bili_login` 扫码，配了才能下 1080P 及以上 |
| `PROXY` | 空 | 全局代理，作用于媒体下载与自建请求 |
| `GITHUB_TOKEN` | 空 | 建议填：免 token 只有 60 次/小时，且按出口 IP 计，共享 IP 下极易被限流 |
| `CACHE_TTL_HOURS` | 24 小时 | 缓存保留时长，0 = 不自动清理 |

其余（Steam 地区与史低 key、网页截图后端、卡片外观、媒体发送、小红书 / Pixiv Cookie 等）
都在那一页里。卡片外观建议直接在「外观 → 卡片设计器」里调。

## Docker 分容器部署：视频发不出去

AstrBot 把图片和语音转成 base64 发出，**视频却是原样带文件路径**（`file:///...`）——
所以 AstrBot 与 NapCat 等协议端不在同一个容器时，图文和语音正常，只有视频发不出去。
两种解法，配一个即可：

**① 共享缓存目录** —— 配「媒体发送 → 共享缓存目录」填一个容器内路径，并让所有相关容器
把宿主机同一个目录挂到**同一个绝对路径**上，例如：

```yaml
services:
  astrbot:
    volumes:
      - /srv/astrbot/data/shared:/app/sharedFolder/denia_share   # 用绝对路径
  napcat:
    volumes:
      - /srv/astrbot/data/shared:/app/sharedFolder/denia_share   # 必须是同一路径
```

然后配置里填 `/app/sharedFolder/denia_share/cache`。

**② 媒体中转** —— 配「媒体发送 → 启用媒体中转」，把下载好的视频注册成 AstrBot 的临时
HTTP 链接再发送，协议端只要能访问那个地址就行，**不需要共享挂载**；同一 Docker 网络里
可直接填 `http://astrbot:6185`。

两种方式失败都会**回退成本地文件发送**，不会把视频丢掉。总览页检测到「在容器里但两条路
都没铺」时会给出提示。

## 自定义解析器

想加第 12 个平台（或改掉某个内置平台的行为），不用改插件代码：把一个 `.py` 文件放进
插件数据目录的 `custom_parsers/`，点网页界面「解析 → 自定义解析器」的「重新加载」即生效，
之后群里发链接一样会被解析。

**说明就在那个目录里** —— 首次运行会写入一份 `README.md`（用法、与内置平台的优先级规则、
接口版本、加载失败原因）和一份 `TEMPLATE.py.txt` 模板，复制模板改一改即可。
加载状态与失败原因显示在「解析 → 自定义解析器」卡上，不用翻日志。

> ⚠️ 那个目录里的文件会被**直接执行**，权限等同于插件自身。只放自己写的、或完整读懂的代码。

## 许可

MIT，详见 [LICENSE](LICENSE)。引用了两处第三方代码：

| 来源 | 许可 | 用到哪里 |
| --- | --- | --- |
| [astrbot_plugin_rika_share](https://github.com/iris1598/astrbot_plugin_rika_share) | MIT | 解析框架、卡片渲染器，以及 B站 / 微博 / 小红书 / AcFun / NGA 的解析实现等 |
| [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2) | Apache-2.0 | 抖音 `a_bogus` 签名（`core/parsers/douyin/sign.py`） |

其余部分（GitHub / Pixiv / Steam 解析、网页界面与外观自定义、媒体发送、卡片外观配置项等）
为本项目实现。Apache-2.0 全文随包附在 `LICENSES/Apache-2.0.txt`，相关源文件头都带来源说明。
