"""小黑盒（xiaoheihe.cn）解析器 —— 支持社区帖子与游戏详情。

## 数据来源（都验证过可用，2026-09-29）

- 帖子：``api.xiaoheihe.cn/bbs/app/link/tree``
- 游戏：``api.xiaoheihe.cn/game/get_game_detail/``
- 游戏简介：``api.xiaoheihe.cn/game/game_introduction/``

三个接口都要求 **hkey 签名**（见 ``RequestSigner``）。这套算法与
``astrbot_plugin_multi_parser/platforms/xiaoheihe/signing.py`` 一致 ——
小黑盒前端把参数表与「时间戳/随机数/路径」做交错哈希后再查表替换，
没有签名会被判成非法请求（实测返回 `status=failed`）。

## 无需 Cookie

三个接口实测**匿名可用**。仅有极少数受限内容需要登录，届时返回
``show_captcha`` / ``denied`` 之类的业务错误，本解析器会把它们翻成人话。

## 支持链接形态

- https://www.xiaoheihe.cn/app/bbs/link/<link_id>
- https://api.xiaoheihe.cn/v3/bbs/app/api/web/share?link_id=<link_id>
- https://www.xiaoheihe.cn/app/topic/game/<game_type>/<appid>
- https://api.xiaoheihe.cn/game/share_game_detail?appid=<appid>&game_type=<game_type>
"""

PARSER_API_VERSION = 1

PLATFORM_NAME = "小黑盒"
PLATFORM_CARD_NAME = "小黑盒"

import hashlib
import html
import json
import random
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from astrbot.api import logger


# ---- 导入插件自身的模块 ----
# 不能写 `from astrbot_plugin_denia_share.core...`（模板里的写法）：插件在这个
# 部署下被 AstrBot 挂成 `data.plugins.astrbot_plugin_denia_share`，顶层名不存在。
# 也不能用相对导入：自定义解析器是 spec_from_file_location 建出来的顶层模块，
# __package__ 为空。这里从 sys.modules 里按后缀反查，插件被挂成什么名字都能找到。
def _plugin_module():
    import sys
    for name, mod in sys.modules.items():
        if name.endswith(("astrbot_plugin_denia_share",
                         "astrbot_plugin_glass_share")) and hasattr(mod, "__path__"):
            return mod
    raise ImportError("找不到 astrbot_plugin_denia_share 模块（插件未加载？）")


_plugin = _plugin_module()
BaseParser = _plugin.core.base_parser.BaseParser
handle = _plugin.core.base_parser.handle
ParseException = _plugin.core.base_parser.ParseException
platform_of = _plugin.core.data.platform_of

API = "https://api.xiaoheihe.cn"

# 通用请求头。Referer/Origin 必须是 xiaoheihe.cn —— 缺失时接口会拒绝。
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.xiaoheihe.cn/",
    "Origin": "https://www.xiaoheihe.cn",
}

# 接口通用的平台标识参数（照抄前端，缺项会被判非法）
COMMON_PARAMS = {
    "app": "heybox",
    "os_type": "web",
    "x_app": "heybox_website",
    "x_client_type": "web",
    "x_os_type": "Windows",
    "x_client_version": "",
    "client_type": "web",
    "web_version": "3.0",
    "version": "999.0.4",
}


class RequestSigner:
    """生成小黑盒接口要求的 hkey / _time / nonce。

    算法还原自前端：把「时间戳+1、规范化路径、随机 nonce」三串分别做
    「字符表映射」后**交错拼接**，取前 20 字符做 md5，再对 md5 前 5 位做
    反向字符表映射、对后 6 位做逐列混淆取模 100，拼成最终 hkey。
    """

    CHAR_TABLE = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"

    def sign_path(self, path: str) -> dict[str, str | int]:
        now = int(time.time())
        nonce = hashlib.md5(
            (str(now) + str(random.random())).encode()
        ).hexdigest().upper()
        return {"hkey": self.ov(path, now + 1, nonce), "_time": now, "nonce": nonce}

    def ov(self, path: str, timestamp: int, nonce: str) -> str:
        # 路径规范化：去掉空段、补成 /a/b/ 形态，签名与实际请求路径必须一致
        normalized = "/" + "/".join(p for p in path.split("/") if p) + "/"
        interleaved = self.interleave([
            self.av(str(timestamp), -2),
            self.sv(normalized),
            self.sv(nonce),
        ])[:20]
        digest = hashlib.md5(interleaved.encode()).hexdigest()
        prefix = self.av(digest[:5], -4)
        suffix = str(
            sum(self.mix_columns([ord(c) for c in digest[-6:]])) % 100
        ).zfill(2)
        return prefix + suffix

    def av(self, text: str, cut: int) -> str:
        table = self.CHAR_TABLE[:cut]
        return "".join(table[ord(c) % len(table)] for c in text)

    def sv(self, text: str) -> str:
        return "".join(self.CHAR_TABLE[ord(c) % len(self.CHAR_TABLE)] for c in text)

    @staticmethod
    def interleave(parts: list[str]) -> str:
        result = []
        for i in range(max(len(p) for p in parts)):
            for p in parts:
                if i < len(p):
                    result.append(p[i])
        return "".join(result)

    # --- GF(2^8) 有限域乘法，用于末 6 字符的列混淆 ---
    @staticmethod
    def xtime(value: int) -> int:
        return ((value << 1) ^ 27) & 0xFF if value & 128 else value << 1

    @classmethod
    def mul3(cls, v): return cls.xtime(v) ^ v
    @classmethod
    def mul6(cls, v): return cls.mul3(cls.xtime(v))
    @classmethod
    def mul12(cls, v): return cls.mul6(cls.mul3(cls.xtime(v)))
    @classmethod
    def mul14(cls, v): return cls.mul12(v) ^ cls.mul6(v) ^ cls.mul3(v)

    @classmethod
    def mix_columns(cls, column: list[int]) -> list[int]:
        v = list(column)
        while len(v) < 4:
            v.append(0)
        m = [
            cls.mul14(v[0]) ^ cls.mul12(v[1]) ^ cls.mul6(v[2]) ^ cls.mul3(v[3]),
            cls.mul3(v[0]) ^ cls.mul14(v[1]) ^ cls.mul12(v[2]) ^ cls.mul6(v[3]),
            cls.mul6(v[0]) ^ cls.mul3(v[1]) ^ cls.mul14(v[2]) ^ cls.mul12(v[3]),
            cls.mul12(v[0]) ^ cls.mul6(v[1]) ^ cls.mul3(v[2]) ^ cls.mul14(v[3]),
        ]
        if len(v) > 4:
            m.extend(v[4:])
        return m


# ============================ 文本/URL 工具 ============================

def clean_text(text: str) -> str:
    """清理小黑盒正文里的 HTML 实体与冗余空白。"""
    value = html.unescape(str(text).replace("\xa0", " "))
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def strip_tags(text: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", "", html.unescape(str(text))))


def normalize_image_url(value) -> str:
    """规范化图片地址。

    小黑盒同一张图有 ``imgheybox1.max-c.com`` / ``imgheybox.max-c.com`` 两个
    等价域名，统一到后者以便去重（这点与 multi_parser 的处理保持一致）。
    """
    if not isinstance(value, str) or not value:
        return ""
    normalized = html.unescape(value).strip()
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    if not normalized.startswith(("http://", "https://")):
        return ""
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return normalized
    if (parsed.hostname or "").lower() == "imgheybox1.max-c.com":
        parsed = parsed._replace(netloc="imgheybox.max-c.com")
    return urlunsplit(parsed)


def image_dedup_key(url: str) -> str:
    return url.split("?", 1)[0].replace("imgheybox1.max-c.com", "imgheybox.max-c.com")


class _PostBodyParser(HTMLParser):
    """按可见顺序从帖子正文片段里抽出「文字段落」和「图片」。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in {"p", "div", "li", "blockquote", "br"}:
            self._flush()
        if tag == "img":
            self._flush()
            a = dict(attrs)
            url = a.get("data-original") or a.get("data-src") or a.get("src") or ""
            if url:
                self.items.append(("image", str(url)))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self._skip = max(0, self._skip - 1)
            return
        if not self._skip and tag in {"p", "div", "li", "blockquote"}:
            self._flush()

    def handle_data(self, data):
        if not self._skip and (t := data.strip()):
            self._buf.append(t)

    def close(self):
        super().close()
        self._flush()

    def _flush(self):
        text = " ".join(self._buf).strip()
        self._buf.clear()
        if text:
            self.items.append(("text", text))


def parse_post_body(raw_text) -> list[tuple[str, str]]:
    """把 ``link.text`` 解析成 [('text'|'image', value)] 有序列表。

    ``text`` 字段是一段 JSON 数组，每项要么是 img 块、要么是含 HTML 的 text 块。
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return []
    try:
        blocks = json.loads(raw_text)
    except json.JSONDecodeError:
        return [("text", clean_text(raw_text))] if clean_text(raw_text) else []
    if not isinstance(blocks, list):
        return [("text", clean_text(raw_text))] if clean_text(raw_text) else []

    items: list[tuple[str, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") == "img":
            if url := normalize_image_url(block.get("url")):
                items.append(("image", url))
            continue
        fragment = str(block.get("text") or "")
        if not fragment:
            continue
        parser = _PostBodyParser()
        parser.feed(fragment)
        parser.close()
        for kind, value in parser.items:
            if kind == "image":
                if url := normalize_image_url(value):
                    items.append(("image", url))
            elif cleaned := clean_text(value):
                items.append(("text", cleaned))
    return items


# ============================ 解析器 ============================


class XiaoheiheParser(BaseParser):
    platform = platform_of("xiaoheihe")

    def __init__(self, downloader):
        super().__init__(downloader)
        self._signer = RequestSigner()

    # ---- 链接匹配 ----
    @handle("xiaoheihe.cn", r"xiaoheihe\.cn/app/bbs/link/(?P<link_id>[0-9a-zA-Z]+)")
    async def _parse_bbs_web(self, searched):
        return await self._fetch_post(searched.group("link_id"))

    @handle("api.xiaoheihe.cn", r"api\.xiaoheihe\.cn/v3/bbs/app/api/(?:web/)?share\?[^\s#]*\blink_id=(?P<sid>[0-9a-zA-Z]+)")
    async def _parse_bbs_share(self, searched):
        return await self._fetch_post(searched.group("sid"))

    @handle("topic/game", r"xiaoheihe\.cn/app/topic/game/(?P<gtype>[a-z]+)/(?P<appid>[0-9a-zA-Z]+)")
    async def _parse_game_web(self, searched):
        return await self._fetch_game(searched.group("appid"), searched.group("gtype"))

    @handle("share_game_detail", r"api\.xiaoheihe\.cn/game/share_game_detail\?[^\s#]*\bappid=(?P<appid>[0-9a-zA-Z]+)[^\s#]*\bgame_type=(?P<gtype>[a-z]+)")
    async def _parse_game_share(self, searched):
        return await self._fetch_game(searched.group("appid"), searched.group("gtype"))

    # ---- 请求工具 ----
    async def _get_json(self, path: str, params: dict) -> dict:
        url = f"{API}{path}"
        async with self.new_client() as client:
            resp = await client.get(
                url,
                params={**params, **self._signer.sign_path(path)},
                headers={**self.headers, **HEADERS},
            )
            resp.raise_for_status()
            payload = resp.json()

        if not isinstance(payload, dict):
            raise ParseException("小黑盒返回的不是 JSON 对象")
        status = str(payload.get("status") or "").lower()
        if status != "ok":
            # 把业务错误翻译成人话。这些都不是「解析器写错了」，而是
            # 内容层面的限制（链接失效 / 需要登录 / 触发风控）。
            msg = str(payload.get("msg") or payload.get("message") or "").strip()
            if status in {"show_captcha", "captcha"} or "captcha" in msg.lower():
                raise ParseException("小黑盒触发了人机验证，请稍后再试")
            if any(k in msg.lower() for k in ("login", "token", "登录")):
                raise ParseException(f"小黑盒要求登录：{msg or '请配置 Cookies'}")
            raise ParseException(f"小黑盒返回失败（status={status}）：{msg or '无详情'}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ParseException("小黑盒返回的 result 为空")
        return result

    # ---- 帖子 ----
    async def _fetch_post(self, link_id: str):
        result = await self._get_json("/bbs/app/link/tree", {
            **COMMON_PARAMS,
            "link_id": link_id,
            "is_first": "1", "page": "1", "index": "1",
            "limit": "20", "owner_only": "0",
        })
        link = result.get("link")
        if not isinstance(link, dict):
            raise ParseException("小黑盒帖子数据缺少 link 节点")

        user = link.get("user") if isinstance(link.get("user"), dict) else {}
        author_name = clean_text(str(user.get("username") or user.get("nickname") or "")) or None
        author = self.create_author(
            author_name or "小黑盒用户",
            normalize_image_url(user.get("avatar")) or None,
        )

        title = clean_text(str(link.get("title") or "")) or "小黑盒帖子"
        body = parse_post_body(link.get("text"))

        result_obj = self.result(
            url=f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
            title=title,
            author=author,
            timestamp=_parse_ts(link.get("create_at")),
            extra={"content_type": "帖子"},
        )

        # 正文与图片按原始顺序交错：文字进 text，图片进 contents。
        # 卡片会把 contents 里的图片排成网格，所以顺序信息只能体现在文字里，
        # 这里保留完整文字（含段落换行），不为了对齐图片而把文字切碎。
        texts: list[str] = []
        for kind, value in body:
            if kind == "text":
                texts.append(value)
            else:
                result_obj.contents.append(self.create_image(value))
        if texts:
            result_obj.text = "\n\n".join(texts)

        # 视频：has_video 为真时才有 video_url
        if link.get("has_video") and (vurl := str(link.get("video_url") or "").strip()):
            # 时长字段名不同版本可能不同，逐个试；取不到就是 None（卡片不显示时长）
            duration = None
            for key in ("video_duration", "duration", "video_time"):
                if (raw := link.get(key)) not in (None, "", 0, "0"):
                    try:
                        duration = float(raw)
                        break
                    except (TypeError, ValueError):
                        continue
            cover = None
            for cand in (link.get("video_thumb"), link.get("video_cover")):
                if cover := normalize_image_url(cand):
                    break
            result_obj.contents.append(self.create_video(vurl, cover, duration=duration))
            if desc := clean_text(str(link.get("description") or "")):
                result_obj.text = (result_obj.text + "\n\n" + desc).strip() if result_obj.text else desc
        return result_obj

    # ---- 游戏 ----
    async def _fetch_game(self, appid: str, game_type: str):
        common = {**COMMON_PARAMS, "steam_appid": appid}
        game = await self._get_json("/game/get_game_detail/", common)

        # 名称：优先中文名（name），括号里补英文名（name_en）
        cn = clean_text(str(game.get("name") or ""))
        en = clean_text(str(game.get("name_en") or ""))
        title = f"{cn}（{en}）" if cn and en else (cn or en or f"小黑盒游戏 {appid}")

        # 简介接口只需要 steam_appid，缺了也不影响主流程
        intro: dict = {}
        steam_appid = game.get("steam_appid") or appid
        try:
            intro = await self._get_json(
                "/game/game_introduction/",
                {"steam_appid": steam_appid, "return_json": 1},
            )
        except Exception as exc:
            logger.debug(f"[xiaoheihe] 游戏简介获取失败（忽略）: {exc}")

        # 描述：简介 + 类型 + 评分 + 价格等
        lines: list[str] = []
        about = str(intro.get("about_the_game") or game.get("about_the_game") or "")
        if about_text := strip_tags(about):
            lines.append(about_text[:400])
        if types := _game_types(game):
            lines.append(f"类型：{types}")
        if score := str(game.get("score") or "").strip():
            stats = game.get("comment_stats")
            count = stats.get("score_comment") if isinstance(stats, dict) else None
            lines.append(
                f"小黑盒评分：{score}（{_people(count)}）"
                if isinstance(count, int) and count > 0 else f"小黑盒评分：{score}"
            )
        if release := str(intro.get("release_date") or "").strip():
            lines.append(f"发布时间：{release.replace('-', '.')}")
        if dev := _companies(intro.get("developers")):
            lines.append(f"开发商：{dev}")
        if pub := _companies(intro.get("publishers")):
            lines.append(f"发行商：{pub}")

        result = self.result(
            url=f"https://www.xiaoheihe.cn/app/topic/game/{game_type}/{appid}",
            title=title,
            text="\n\n".join(lines) or None,
            author=self.create_author("小黑盒", None),
            extra={"content_type": "游戏", "stats_line": f"平台 {str(game_type).upper()}"},
        )

        # 封面 + 截图（screenshots 里混了 image 和 movie 两类）
        shots = game.get("screenshots")
        images: list[str] = []
        seen: set[str] = set()
        if isinstance(shots, list):
            for item in shots:
                if not isinstance(item, dict) or item.get("type") == "movie":
                    continue
                for field in ("url", "thumbnail"):
                    if url := normalize_image_url(item.get(field)):
                        key = image_dedup_key(url)
                        if key not in seen:
                            seen.add(key)
                            images.append(url)
                            break
        if cover := normalize_image_url(game.get("image") or game.get("share_img")):
            key = image_dedup_key(cover)
            if key not in seen:
                images.insert(0, cover)
                seen.add(key)
        for url in images[:9]:  # 卡片网格放不下更多，9 张是 3x3 上限
            result.contents.append(self.create_image(url))

        # 预告片：取第一个非 m3u8 的（m3u8 由插件下载器自己处理，但 Steam CDN
        # 的 m3u8 常带防盗链，优先给 mp4）
        if isinstance(shots, list):
            movies = [
                normalize_image_url(s.get("url") or s.get("video_url"))
                for s in shots
                if isinstance(s, dict) and s.get("type") == "movie"
            ]
            movies = [m for m in movies if m]
            if movies:
                # cover 传已取到的截图：**不要传 None** —— 传 None 会走插件
                # 「下载整个视频再抽第一帧当封面」的分支，白下一遍几十 MB 的
                # 预告片只为了拿一张图，而我们手上本来就有截图。
                result.contents.append(
                    self.create_video(movies[0], images[0] if images else None)
                )
        return result


def _people(count) -> str:
    try:
        n = int(count)
    except (TypeError, ValueError):
        return ""
    return f"{n / 10000:.1f} 万人评价" if n >= 10000 else f"{n} 人评价"


def _companies(items) -> str:
    if not isinstance(items, list):
        return ""
    return "、".join(
        str(i["value"]) for i in items
        if isinstance(i, dict) and i.get("value")
    )


def _game_types(game: dict) -> str:
    """从 common_tags 里抽类型：steam_aggre 是通用标签，simple_tag 是分类。"""
    tags = game.get("common_tags")
    if not isinstance(tags, list):
        return ""
    common, cats = [], []
    for item in tags:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "steam_aggre" and isinstance(item.get("desc_list"), list):
            common.extend(clean_text(str(v)) for v in item["desc_list"] if v)
        elif item.get("type") == "simple_tag" and item.get("desc"):
            cats.append(clean_text(str(item["desc"])))
    parts = []
    if common:
        parts.append(" ".join(common).replace("  ", " ").strip())
    if cats:
        parts.append("、".join(cats))
    return " | ".join(parts)


def _parse_ts(value):
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    # 接口给的是秒级时间戳；异常小值（如 0）当没有
    return ts if ts > 0 else None
