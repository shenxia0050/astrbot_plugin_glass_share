"""QQ音乐解析器 —— 解析单曲/专辑分享链接，渲染成分享卡片。

数据来源：
- 单曲：``c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg``
- 专辑：``c.y.qq.com/v8/fcg-bin/fcg_v8_album_info_cp.fcg``
两者都是免登录的公开 fcg 接口，只需带 ``Referer: https://y.qq.com/``。

封面 URL 有稳定规律，无需额外请求：
    https://y.gtimg.cn/music/photo_new/T002R800x800M000{album_mid}.jpg

同样**不提供音频直链**：fcg 接口只给元信息，播放地址要走 vkey 接口，
那条路径需要 GUID 与防盗链参数，且多数歌曲要会员/购买，不适合做卡片。

支持链接形态：
- https://y.qq.com/n/ryqq/songDetail/0039MnYb0qxYhV
- https://i.y.qq.com/v8/playsong.html?songmid=0039MnYb0qxYhV
- https://y.qq.com/n/ryqq/albumDetail/000MkMni19ClKG
- 站外短链 https://c6.y.qq.com/base/fcgi-bin/u?__=xxxx（先跟跳转）
"""

PARSER_API_VERSION = 1

PLATFORM_NAME = "QQ音乐"
PLATFORM_CARD_NAME = "QQ音乐"

import re

from astrbot.api import logger

# ---- 导入插件自身的模块 ----
# 不能写 `from astrbot_plugin_denia_share.core...`（模板里的写法）：插件在这个
# 部署下被 AstrBot 挂成 `data.plugins.<插件名>`，顶层名不存在。也不能用相对导入：
# 自定义解析器是 spec_from_file_location 建出来的顶层模块，__package__ 为空。
# 下面按「本文件所在的数据目录名」反查对应插件包，denia / glass 谁加载都能对上。
def _plugin_module():
    """反查本文件所属的插件模块。

    自定义解析器固定放在 ``<插件数据目录>/custom_parsers/`` 下，而数据目录名
    就是插件名（``astrbot_plugin_denia_share`` / ``astrbot_plugin_glass_share``），
    据此取出「本文件属于哪个插件」，再按名字去 ``sys.modules`` 里取对应包。

    不能只按两个后缀遍历 sys.modules：denia 与 glass 可能在同一进程里同时加载，
    dict 顺序取到的可能是另一个插件的包，那样 BaseParser 就不是加载器用来校验的
    那一个，会被误判成「文件里没有 BaseParser 的子类」。
    """
    import sys
    from pathlib import Path

    candidates = []
    try:
        # .../plugin_data/<plugin_name>/custom_parsers/<file>.py
        candidates.append(Path(__file__).resolve().parent.parent.name)
    except NameError:  # pragma: no cover - spec 加载时一定有 __file__
        pass
    for fallback in ("astrbot_plugin_glass_share", "astrbot_plugin_denia_share"):
        if fallback not in candidates:
            candidates.append(fallback)

    for candidate in candidates:
        for name, mod in sys.modules.items():
            if (
                name == candidate
                or name.endswith("." + candidate)
            ) and hasattr(mod, "__path__"):
                return mod
    raise ImportError(
        f"找不到插件模块（候选：{', '.join(candidates)}；插件未加载？）"
    )


_plugin = _plugin_module()
BaseParser = _plugin.core.base_parser.BaseParser
handle = _plugin.core.base_parser.handle
ParseException = _plugin.core.base_parser.ParseException
platform_of = _plugin.core.data.platform_of


SONG_API = "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg"
ALBUM_API = "https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_info_cp.fcg"

# 封面地址模板。T002 = 专辑图，R800x800 = 800x800，M000 = 固定前缀。
COVER_TMPL = "https://y.gtimg.cn/music/photo_new/T002R800x800M000{mid}.jpg"

HEADERS = {
    "Referer": "https://y.qq.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _hms(seconds: int | float | None) -> str:
    total = int(seconds or 0)
    if total <= 0:
        return ""
    return f"{total // 60}:{total % 60:02d}"


class QQMusicParser(BaseParser):
    platform = platform_of("qq_music")

    # ---- 短链 ----
    @handle("c6.y.qq.com", r"c6\.y\.qq\.com/base/fcgi-bin/u\?__=(?P<code>[A-Za-z0-9]+)")
    async def _parse_short(self, searched):
        code = searched.group("code")
        async with self.new_client(follow_redirects=True) as client:
            resp = await client.get(
                f"https://c6.y.qq.com/base/fcgi-bin/u?__={code}",
                headers={**self.headers, **HEADERS},
            )
            final = str(resp.url)
        logger.debug(f"[qqmusic] 短链 {code} 最终跳转到 {final}")
        # search_url() 返回 (keyword, match)：keyword 是字符串，不是解析器实例，
        # 所以这里不能用它做二次分发 —— 直接按最终 URL 的形态判断。
        return await self._dispatch(final)

    # ---- 单曲 ----
    @handle("y.qq.com", r"y\.qq\.com/n/ryqq/songDetail/(?P<mid>\w+)")
    async def _parse_songdetail(self, searched):
        return await self._fetch_song(searched.group("mid"))

    @handle("i.y.qq.com", r"i\.y\.qq\.com/v8/playsong\.html\?[^\s]*?songmid=(?P<mid>\w+)")
    async def _parse_playsong(self, searched):
        return await self._fetch_song(searched.group("mid"))

    # ---- 专辑 ----
    @handle("albumDetail", r"y\.qq\.com/n/ryqq/albumDetail/(?P<mid>\w+)")
    async def _parse_album(self, searched):
        return await self._fetch_album(searched.group("mid"))

    # ---- 实现 ----
    async def _fetch_song(self, song_mid: str):
        async with self.new_client() as client:
            resp = await client.get(
                SONG_API,
                params={"songmid": song_mid, "platform": "yqq", "format": "json"},
                headers={**self.headers, **HEADERS},
            )
            resp.raise_for_status()
            payload = resp.json()

        data = payload.get("data") or []
        if not data:
            raise ParseException(
                f"QQ音乐未返回歌曲数据（mid={song_mid}，code={payload.get('code')}）"
            )
        song = data[0]

        name = (song.get("name") or "").strip() or f"歌曲 {song_mid}"
        # singer 一定是列表（合唱/feat. 会有多个）
        singers = [s.get("name") for s in (song.get("singer") or []) if s.get("name")]
        album = song.get("album") or {}
        album_mid = album.get("mid")
        album_name = (album.get("name") or "").strip()
        interval = song.get("interval")  # 秒

        cover = COVER_TMPL.format(mid=album_mid) if album_mid else None

        stats = []
        if genres := _first(song.get("genre")):
            stats.append(f"🎵 {genres}")
        if lang := _lang_name(song.get("lan")):
            stats.append(lang)

        result = self.result(
            url=f"https://y.qq.com/n/ryqq/songDetail/{song_mid}",
            title=name,
            text=f"专辑: {album_name}" if album_name else None,
            author=self.create_author("、".join(singers) or "未知歌手", cover),
            extra={
                "content_type": "单曲",
                "duration": _hms(interval),
                "stats_line": " · ".join(stats),
            },
        )
        if cover:
            result.contents.append(self.create_image(cover))
        return result

    async def _fetch_album(self, album_mid: str):
        async with self.new_client() as client:
            resp = await client.get(
                ALBUM_API,
                params={"albummid": album_mid, "platform": "yqq", "format": "json"},
                headers={**self.headers, **HEADERS},
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("code") != 0:
            raise ParseException(
                f"QQ音乐专辑接口返回异常（code={payload.get('code')}）"
            )
        album = payload.get("data") or {}
        if not album:
            raise ParseException(f"QQ音乐未返回专辑数据（mid={album_mid}）")

        name = (album.get("name") or "").strip() or f"专辑 {album_mid}"
        # 专辑接口是扁平字段（singername/singermid），不是嵌套的 singer 对象 ——
        # 写成 (album.get("singer") or {}).get("name") 会永远拿到 None，
        # 表现为卡片上歌手显示「未知歌手」。
        singer = (album.get("singername") or "").strip() or "未知歌手"
        songs = album.get("list") or []
        cover = COVER_TMPL.format(mid=album_mid)

        stats = []
        if count := album.get("cur_song_num"):
            stats.append(f"💿 {count} 首")
        if year := (album.get("aDate") or "")[:4]:
            stats.append(f"📅 {year}")

        desc = (album.get("desc") or "").strip()

        # 专辑名后面接曲目表（最多 10 首，避免正文过长把卡片撑爆）
        text_lines = []
        if desc:
            text_lines.append(desc[:200])
        if songs:
            names = [s.get("songname") or s.get("name") for s in songs[:10]]
            names = [n for n in names if n]
            if names:
                more = f" 等 {len(songs)} 首" if len(songs) > len(names) else ""
                text_lines.append("曲目: " + "、".join(names) + more)

        result = self.result(
            url=f"https://y.qq.com/n/ryqq/albumDetail/{album_mid}",
            title=name,
            text="\n".join(text_lines) or None,
            author=self.create_author(singer, cover),
            extra={
                "content_type": "专辑",
                "stats_line": " · ".join(stats),
            },
        )
        result.contents.append(self.create_image(cover))
        return result

    async def _dispatch(self, url: str):
        """短链跳转后的二次分发：按最终 URL 形态挑处理函数。

        短链会跳到 songDetail / playsong.html / albumDetail 三种形态之一，
        这里集中判断，避免在 _parse_short 里堆三层 if。
        """
        if m := re.search(r"albumDetail/(\w+)", url):
            return await self._fetch_album(m.group(1))
        if m := re.search(r"songDetail/(\w+)", url):
            return await self._fetch_song(m.group(1))
        if m := re.search(r"songmid=(\w+)", url):
            return await self._fetch_song(m.group(1))
        raise ParseException(f"无法从跳转地址识别歌曲或专辑: {url}")


def _first(v):
    """接口的 genre/lan 有时是字符串、有时是列表，统一取首个非空值。"""
    if isinstance(v, list):
        return v[0] if v else None
    return v


_LANG = {"0": "国语", "3": "日语", "5": "粤语", "6": "英语", "7": "韩语"}


def _lang_name(v) -> str:
    return _LANG.get(str(_first(v) or ""), "")
