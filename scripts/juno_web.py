#!/usr/bin/env python3
"""Web search for Juno research skill — multi-provider fallbacks."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
JUNO_UA = "Juno-Agent/1.1 (+https://github.com)"


def _http_get(url: str, *, timeout: float = 8, ua: str = BROWSER_UA) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _dedupe_results(results: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        url = (r.get("url") or "").strip()
        key = url or (r.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _ddg_instant(query: str, max_results: int) -> list[dict]:
    ia_url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
    )
    results: list[dict] = []
    try:
        req = urllib.request.Request(ia_url, headers={"User-Agent": JUNO_UA})
        # Short timeout — DDG often blocked in CN; don't burn the whole budget
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        abstract = (data.get("AbstractText") or "").strip()
        if abstract:
            results.append(
                {
                    "title": data.get("Heading") or query,
                    "url": data.get("AbstractURL") or "",
                    "snippet": abstract,
                    "source": "ddg-instant",
                }
            )
        for topic in (data.get("RelatedTopics") or []):
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": topic.get("Text", "")[:120],
                        "url": topic.get("FirstURL") or "",
                        "snippet": topic.get("Text", "")[:240],
                        "source": "ddg-instant",
                    }
                )
            elif isinstance(topic, dict):
                for sub in topic.get("Topics") or []:
                    if sub.get("Text"):
                        results.append(
                            {
                                "title": sub.get("Text", "")[:120],
                                "url": sub.get("FirstURL") or "",
                                "snippet": sub.get("Text", "")[:240],
                                "source": "ddg-instant",
                            }
                        )
            if len(results) >= max_results:
                break
    except Exception:
        pass
    return results[:max_results]


def _bing_html(query: str, max_results: int) -> list[dict]:
    """Bing HTML search — usually reachable in China without VPN."""
    results: list[dict] = []
    endpoints = [
        "https://cn.bing.com/search?" + urllib.parse.urlencode({"q": query, "setlang": "zh-CN"}),
        "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "setlang": "zh-CN"}),
    ]
    # Bing SERP: <li class="b_algo"> … <h2><a href="…">title</a></h2> … <p>snippet</p>
    algo_re = re.compile(
        r'<li[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>([\s\S]*?)</li>',
        re.I,
    )
    link_re = re.compile(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', re.I)
    snippet_re = re.compile(r'<p[^>]*>([\s\S]*?)</p>', re.I)
    tag_re = re.compile(r"<[^>]+>")

    for html_url in endpoints:
        if len(results) >= max_results:
            break
        try:
            html = _http_get(html_url, timeout=6)
        except Exception:
            continue
        for block in algo_re.finditer(html):
            chunk = block.group(1)
            m = link_re.search(chunk)
            if not m:
                continue
            url = unescape(m.group(1)).strip()
            title = tag_re.sub("", unescape(m.group(2))).strip()
            if not url.startswith("http"):
                continue
            if "bing.com" in url and "/search" in url:
                continue
            sn = snippet_re.search(chunk)
            snippet = tag_re.sub("", unescape(sn.group(1))).strip() if sn else ""
            results.append(
                {
                    "title": title[:160],
                    "url": url,
                    "snippet": snippet[:240],
                    "source": "bing-html",
                }
            )
            if len(results) >= max_results:
                break
        if results:
            break
    return results[:max_results]


def _ddg_html(query: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    # One endpoint only — second lite URL often stalls behind the firewall
    endpoints = [
        "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
    ]
    patterns = [
        re.compile(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
            re.I,
        ),
        re.compile(r'<a[^>]+class="[^"]*result-link[^"]*"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', re.I),
        re.compile(r'<a[^>]+rel="nofollow"[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>', re.I),
    ]
    snippet_re = re.compile(r'class="result__snippet"[^>]*>([^<]*)', re.I)

    for html_url in endpoints:
        if len(results) >= max_results:
            break
        try:
            html = _http_get(html_url, timeout=5)
        except Exception:
            continue
        for pat in patterns:
            for m in pat.finditer(html):
                url, title = m.group(1), unescape(m.group(2))
                if url.startswith("//"):
                    url = "https:" + url
                if "duckduckgo.com" in url and "/l/?" not in url:
                    continue
                if url.startswith("/"):
                    continue
                snippet = ""
                sn = snippet_re.search(html, m.end())
                if sn:
                    snippet = unescape(sn.group(1)).strip()
                results.append(
                    {
                        "title": title.strip()[:160],
                        "url": url.strip(),
                        "snippet": snippet[:240],
                        "source": "ddg-html",
                    }
                )
                if len(results) >= max_results:
                    break
            if results:
                break
    return results[:max_results]


def _github_search(query: str, max_results: int) -> list[dict]:
    """GitHub REST search — no API key, low rate limit but reliable for repo discovery."""
    q_lower = query.lower()
    if not any(k in q_lower for k in ("github", "repo", "awesome", "open source", "开源", "框架", "framework", "agent")):
        return []
    # Build GitHub search query
    terms = re.sub(r"\b(github|2025|2026|open\s*source|资源|resources?)\b", " ", query, flags=re.I)
    terms = re.sub(r"\s+", " ", terms).strip() or query
    if "awesome" not in terms.lower() and "agent" in terms.lower():
        terms = f"awesome {terms}"
    api = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": terms[:200], "sort": "stars", "order": "desc", "per_page": max_results}
    )
    results: list[dict] = []
    try:
        req = urllib.request.Request(
            api,
            headers={
                "User-Agent": JUNO_UA,
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in (data.get("items") or [])[:max_results]:
            results.append(
                {
                    "title": item.get("full_name") or item.get("name") or "",
                    "url": item.get("html_url") or "",
                    "snippet": (item.get("description") or "")[:240],
                    "stars": item.get("stargazers_count"),
                    "source": "github-api",
                }
            )
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # Rate limit — return search page as fallback result
            results.append(
                {
                    "title": f"GitHub search: {terms}",
                    "url": "https://github.com/search?" + urllib.parse.urlencode({"q": terms, "type": "repositories"}),
                    "snippet": "GitHub API 限速，请用 web_fetch 打开此搜索页或指定仓库 URL",
                    "source": "github-fallback",
                }
            )
    except Exception:
        pass
    return results


def _curated_fallbacks(query: str) -> list[dict]:
    """Known-good URLs when all search providers fail."""
    q = query.lower()
    out: list[dict] = []
    if any(k in q for k in ("agent", "ai", "awesome", "github", "框架", "开源")):
        seeds = [
            ("awesome-ai-agents", "https://github.com/e2b-dev/awesome-ai-agents", "Curated list of AI agent frameworks"),
            ("awesome-generative-ai", "https://github.com/steven2358/awesome-generative-ai", "Generative AI resources"),
            ("cursor-agent-trace", "https://github.com/cursor/agent-trace", "Cursor official agent-trace"),
            ("langchain", "https://github.com/langchain-ai/langchain", "LangChain agent framework"),
            ("autogen", "https://github.com/microsoft/autogen", "Microsoft AutoGen multi-agent"),
        ]
        for title, url, snippet in seeds:
            if any(w in q for w in title.replace("-", " ").split()) or "agent" in q or "awesome" in q:
                out.append({"title": title, "url": url, "snippet": snippet, "source": "curated"})
    if "github.com/search" not in str(out):
        out.append(
            {
                "title": "GitHub repository search",
                "url": "https://github.com/search?" + urllib.parse.urlencode({"q": query, "type": "repositories"}),
                "snippet": "GitHub 仓库搜索 — 可用 web_fetch 打开",
                "source": "curated",
            }
        )
    return out[:5]


def web_search(query: str, *, max_results: int = 6) -> dict:
    """Search with a hard wall-clock budget — never hang the agent loop."""
    import threading
    import time as _time

    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}

    box: dict = {}

    def _run() -> None:
        results: list[dict] = []
        providers_tried: list[str] = []
        t0 = _time.monotonic()
        budget_s = 7.0

        def _left() -> float:
            return budget_s - (_time.monotonic() - t0)

        # CN-first: Bing usually works; DDG often blocked and must not burn budget first
        for fn, name in (
            (_bing_html, "bing"),
            (_ddg_instant, "ddg-instant"),
            (_github_search, "github"),
            (_ddg_html, "ddg-html"),
        ):
            if len(results) >= max_results or _left() < 1.0:
                break
            providers_tried.append(name)
            try:
                chunk = fn(q, max_results)
                results.extend(chunk or [])
                results = _dedupe_results(results)[:max_results]
            except Exception:
                continue

        if len(results) < max_results:
            providers_tried.append("curated")
            results = _dedupe_results(results + _curated_fallbacks(q))[:max_results]

        abstract = next((r.get("snippet") for r in results if r.get("snippet")), "")
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        if not results:
            box["r"] = {
                "ok": False,
                "error": "未找到搜索结果（网络超时或无命中）",
                "hint": "用已知知识做最合理假设并交付；或 web_fetch 打开具体 URL",
                "suggested_urls": [r["url"] for r in _curated_fallbacks(q) if r.get("url")][:4],
                "providers_tried": providers_tried,
                "elapsed_ms": elapsed_ms,
            }
            return
        box["r"] = {
            "ok": True,
            "query": q,
            "results": results,
            "abstract": abstract,
            "providers": list({r.get("source") for r in results if r.get("source")}),
            "hint": "读完 results 后总结；要图则直接出 mermaid/chart。可用 web_fetch 抓全文",
            "elapsed_ms": elapsed_ms,
        }

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(8.0)
    if th.is_alive() or "r" not in box:
        # Network stalled — still return something so Agent can keep going
        fb = _curated_fallbacks(q)
        return {
            "ok": True,
            "query": q,
            "results": fb,
            "abstract": "",
            "providers": ["timeout-fallback"],
            "hint": "网络搜索超时；以下为兜底链接。请结合常识假设直接交付，勿空等。",
            "elapsed_ms": 8000,
            "timed_out": True,
        }
    return box["r"]
