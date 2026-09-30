"""网易云音乐解析器 —— 解析单曲分享链接，渲染成分享卡片。

数据来源：``music.163.com/api/song/detail``（免登录公开接口）。
它只返回歌曲元信息（歌名/歌手/专辑/时长/封面），**不返回可播放的音频直链** ——
所以卡片是「歌曲信息卡」，不含音频。想发音频需要走 ``/song/enhance/player/url``，
那条路径要处理加密参数与版权校验（``fee``/``st`` 字段），且大量歌曲无版权，
不值得为一张卡片引入。

支持链接形态（都是网易云分享面板会产出的）：
- https://y.music.163.com/m/song?id=347230
- https://music.163.com/#/song?id=347230
- https://music.163.com/song?id=347230
- 站外分享短链 https://163cn.tv/xxxxx（先跟跳转拿到最终地址再提 id）
"""

PARSER_API_VERSION = 1

PLATFORM_NAME = "网易云音乐"
PLATFORM_CARD_NAME = "网易云"

import re

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
    raise ImportError(
        "找不到 astrbot_plugin_denia_share 模块（插件未加载？）"
    )


_plugin = _plugin_module()
BaseParser = _plugin.core.base_parser.BaseParser
handle = _plugin.core.base_parser.handle
ParseException = _plugin.core.base_parser.ParseException
platform_of = _plugin.core.data.platform_of


# 歌曲详情接口。用 /api/ 而不是 /api/v3/：两者都可用，但 /api/ 的返回结构
# 是一层扁平 dict（songs[0].artists / .album / .duration），字段名稳定且无需
# 处理 v3 的缩写（ar / al / dt）；历史上也有第三方依赖旧字段名。
SONG_API = "https://music.163.com/api/song/detail/"

# 该接口对 Referer 敏感：不带 music.163.com 会被判成站外调用而返回风控页。
HEADERS = {
    "Referer": "https://music.163.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fmt_count(n: int | float | None) -> str:
    """把热度区间（接口给的是 0~100 的浮点）转成可读文本。"""
    if not n:
        return ""
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return str(n)


class NeteaseMusicParser(BaseParser):
    platform = platform_of("netease_music")

    # ---- 链接匹配 ----
    # 分开注册多个 handle，而不是写一个大正则：handle 的第一个参数是关键词，
    # 用来在 search_url() 里早退，关键词越准，正常消息的匹配开销越小。
    @handle("163cn.tv", r"163cn\.tv/(?P<code>[A-Za-z0-9]+)")
    async def _parse_short(self, searched):
        """站外短链：先跟跳转，再按最终 URL 走正常解析。

        短链的 id 不在 URL 里，必须先跟随重定向。``follow_redirects=True``
        由 self.new_client 提供的 client_kwargs 决定，这里显式传参覆盖。
        """
        code = searched.group("code")
        async with self.new_client(follow_redirects=True) as client:
            resp = await client.get(
                f"https://163cn.tv/{code}", headers={**self.headers, **HEADERS}
            )
            final = str(resp.url)
        logger.debug(f"[netease] 短链 {code} 最终跳转到 {final}")
        matched = self.search_url(final)
        if not matched or matched[0] == self.platform.name:
            raise ParseException(f"短链未跳转到歌曲页: {final}")
        # 复用同一条解析逻辑，避免两份实现漂移
        return await self._fetch_song(matched[1])

    # (?<!y\.) 是必须的：`music.163.com` 是 `y.music.163.com` 的子串，
    # 不加这个负向后顾，上面那条移动端域名会被这条先吃掉，下面的 _parse_y_music
    # 就成了永远跑不到的死代码（两者结果相同，但留着两个同义 handler 会误导后人）。
    @handle("music.163.com", r"(?<!y\.)music\.163\.com/(?:#/)?song\?id=(?P<sid>\d+)")
    async def _parse_music163(self, searched):
        return await self._fetch_song(searched)

    @handle("y.music.163.com", r"y\.music\.163\.com/m/song\?[^\s]*?id=(?P<sid>\d+)")
    async def _parse_y_music(self, searched):
        return await self._fetch_song(searched)

    # ---- 解析实现 ----
    async def _fetch_song(self, searched: re.Match[str]):
        sid = searched.group("sid")

        async with self.new_client() as client:
            resp = await client.get(
                SONG_API,
                params={"ids": f"[{sid}]"},
                headers={**self.headers, **HEADERS},
            )
            resp.raise_for_status()
            payload = resp.json()

        songs = payload.get("songs") or []
        if not songs:
            # 未登录时风控会返回 code:-462 或空 songs；两者都是「拿不到数据」，
            # 归成 ParseException（会换下一条解析路径），而不是当成策略跳过。
            raise ParseException(
                f"网易云返回空歌曲数据（id={sid}，code={payload.get('code')}）"
            )
        song = songs[0]

        name = (song.get("name") or "").strip() or f"歌曲 {sid}"
        artists = [a.get("name") for a in (song.get("artists") or []) if a.get("name")]
        album = song.get("album") or {}
        album_name = (album.get("name") or "").strip()
        cover = album.get("picUrl")
        duration_ms = song.get("duration") or 0

        # 副标题（歌曲别名，如「(Live)」）。接口的 alias 是列表，取第一条。
        alias = (song.get("alias") or [None])[0]

        stats = []
        if pop := _fmt_count(song.get("popularity")):
            stats.append(f"🔥 热度 {pop}")
        if fee := song.get("fee"):
            # fee 语义：0 免费 / 1 VIP / 4 购买专辑 / 8 低音质免费。
            # 只在非免费时提示，避免每张卡片都挂一条无意义的「免费」。
            fee_text = {1: "VIP", 4: "付费专辑", 8: "低音质免费"}.get(fee)
            if fee_text:
                stats.append(f"💎 {fee_text}")
        if mvid := song.get("mvid"):
            stats.append("🎬 有 MV")

        author = self.create_author(
            "、".join(artists) or "未知歌手",
            # 歌手的 picUrl 在 artists[].picUrl 上，但多数是默认头像，用专辑封面
            # 当作者头像更直观，也和卡片 hero 的视觉来源保持同源。
            cover,
        )

        result = self.result(
            url=f"https://music.163.com/#/song?id={sid}",
            title=name,
            text=f"专辑: {album_name}" if album_name else None,
            author=author,
            extra={
                "content_type": "单曲",
                "duration": _hms(duration_ms),
                "stats_line": " · ".join(stats),
                "info": f"别名: {alias}" if alias else "",
            },
        )
        # 网易云不给音频直链，所以卡片的主体就是封面图。
        if cover:
            result.contents.append(self.create_image(cover))
        return result


def _hms(duration_ms: int) -> str:
    """毫秒转 mm:ss。接口给的是毫秒，卡片 extra.duration 期望的是字符串。"""
    total = int(duration_ms) // 1000
    if total <= 0:
        return ""
    return f"{total // 60}:{total % 60:02d}"
