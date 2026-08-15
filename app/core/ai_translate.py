"""AI 翻译：OpenAI 兼容 API / 百度翻译，带本地 JSON 缓存。

- 批量翻译在后台线程执行（QObject 信号回传进度/结果，线程安全）。
- 顺序：翻译缓存 → 离线词典 → AI（批量）→ 失败逐条重试。
- 结果自动写入缓存文件（AppData），下次直接命中，不重复花钱。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal

SYSTEM_PROMPT = (
    "这是一个用于 AI 图像生成的 Prompt 词库。\n"
    "请将以下英文 Prompt 翻译成自然、准确、适合图像生成语境的中文。\n"
    "只返回翻译结果，不要解释，不要加序号，不要加引号。"
)


@dataclass
class AIConfig:
    enabled: bool = False
    provider: str = "openai"        # openai | baidu
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    concurrency: int = 4
    batch_size: int = 20
    timeout: int = 60
    baidu_appid: str = ""
    baidu_secret: str = ""
    use_cache: bool = True

    def validate(self) -> str | None:
        """返回错误信息；None 表示可用。"""
        if not self.enabled:
            return "AI 翻译未启用（请在 翻译设置 中开启）"
        if self.provider == "openai":
            if not self.api_key:
                return "未填写 API Key"
            if not self.base_url.strip():
                return "未填写 Base URL"
            if not self.model.strip():
                return "未填写 Model"
        elif self.provider == "baidu":
            if not self.baidu_appid or not self.baidu_secret:
                return "百度翻译需要 AppID 和密钥"
        return None

    def normalize(self) -> None:
        """自动修正接口类型：未填 API Key 但填了百度 AppID/密钥时，改用百度。"""
        if self.provider == "openai" and not self.api_key and self.baidu_appid and self.baidu_secret:
            self.provider = "baidu"


# ---------- 翻译缓存 ----------

def default_cache_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base:
        base = str(Path.home() / ".promptlib")
    p = Path(base) / "PromptLibraryManager"
    p.mkdir(parents=True, exist_ok=True)
    return p / "translation_cache.json"


class TranslationCache:
    """英文 → 中文 JSON 缓存（线程安全，原子保存）。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_cache_path()
        self._lock = threading.Lock()
        self.data: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                with self._lock:
                    self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def get(self, key: str) -> str | None:
        key = key.strip()
        with self._lock:
            return self.data.get(key)

    def merge(self, items: dict[str, str]) -> None:
        if not items:
            return
        with self._lock:
            self.data.update(items)
            self.save_locked()

    def save_locked(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def clear(self) -> None:
        with self._lock:
            self.data.clear()
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------- 单次批量请求（可独立测试） ----------

def translate_openai_batch(texts: list[str], cfg: AIConfig) -> list[str]:
    """OpenAI 兼容 chat/completions：一次请求翻译一批，返回按顺序的中文列表。"""
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(texts)},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if len(lines) != len(texts):
        raise ValueError(f"返回行数 {len(lines)} ≠ 请求条数 {len(texts)}")
    return lines


def translate_baidu_batch(texts: list[str], cfg: AIConfig) -> list[str]:
    """百度翻译：q 用换行分隔，逐行返回结果，按顺序对应。"""
    q = "\n".join(texts)
    salt = str(random.randint(100000, 999999))
    sign = hashlib.md5((cfg.baidu_appid + q + salt + cfg.baidu_secret).encode("utf-8")).hexdigest()
    params = urllib.parse.urlencode(
        {"q": q, "from": "en", "to": "zh", "appid": cfg.baidu_appid, "salt": salt, "sign": sign}
    )
    url = "https://fanyi-api.baidu.com/api/trans/vip/translate?" + params
    with urllib.request.urlopen(url, timeout=cfg.timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error_code" in data:
        raise ValueError(f"百度翻译错误 {data['error_code']}: {data.get('error_msg', '')}")
    results = [r["dst"] for r in data.get("trans_result", [])]
    if len(results) != len(texts):
        raise ValueError(f"返回条数 {len(results)} ≠ 请求条数 {len(texts)}")
    return results


def chunk_texts(texts: list[str], size: int, max_bytes: int | None = None) -> list[list[str]]:
    """分批。max_bytes 用于百度等有长度限制的接口。"""
    out: list[list[str]] = []
    cur: list[str] = []
    cur_bytes = 0
    for t in texts:
        nb = len(t.encode("utf-8")) + 1
        if cur and (len(cur) >= size or (max_bytes and cur_bytes + nb > max_bytes)):
            out.append(cur)
            cur = []
            cur_bytes = 0
        cur.append(t)
        cur_bytes += nb
    if cur:
        out.append(cur)
    return out


def _call_batch(texts: list[str], cfg: AIConfig) -> list[str]:
    if cfg.provider == "baidu":
        return translate_baidu_batch(texts, cfg)
    return translate_openai_batch(texts, cfg)


# ---------- 后台批量翻译工作线程 ----------

class TranslateWorker(QObject):
    """在普通 Python 线程中执行批量翻译，通过信号回传（跨线程安全）。"""

    progress = Signal(int, int, str)   # done, total, 当前条目
    finished = Signal(dict, list)      # {text: chinese}, [错误信息]

    def __init__(
        self,
        entries: list[str],
        cfg: AIConfig,
        cache: TranslationCache | None = None,
        dictionary=None,
        cancel_event: threading.Event | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.entries = [e.strip() for e in entries if e and e.strip()]
        self.cfg = cfg
        self.cache = cache
        self.dictionary = dictionary
        self.cancel = cancel_event or threading.Event()

    def run(self) -> None:
        results: dict[str, str] = {}
        errors: list[str] = []
        total = len(self.entries)
        if total == 0:
            self.finished.emit({}, [])
            return

        # 1) 缓存 + 离线词典
        todo: list[str] = []
        for t in self.entries:
            got = None
            if self.cfg.use_cache and self.cache is not None:
                got = self.cache.get(t)
            if got is None and self.dictionary is not None and self.dictionary.loaded:
                got = self.dictionary.translate_entry(t)
            if got:
                results[t] = got
            else:
                todo.append(t)
        self.progress.emit(len(results), total, "")
        if not todo:
            if self.cache is not None:
                self.cache.merge(results)
            self.finished.emit(results, errors)
            return

        # 2) AI 批量
        if not self.cfg.enabled:
            errors.append(self.cfg.validate() or "AI 翻译未启用")
            self.finished.emit(results, errors)
            return

        max_bytes = 3000 if self.cfg.provider == "baidu" else None
        batches = chunk_texts(todo, self.cfg.batch_size, max_bytes)
        done = len(results)
        failed_batches: list[list[str]] = []

        with ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency)) as pool:
            futures = {pool.submit(_call_batch, b, self.cfg): b for b in batches}
            for fut in as_completed(futures):
                if self.cancel.is_set():
                    break
                batch = futures[fut]
                try:
                    lines = fut.result()
                    for t, zh in zip(batch, lines):
                        results[t] = zh
                        done += 1
                        self.progress.emit(done, total, t)
                except Exception as exc:  # noqa: BLE001
                    failed_batches.append(batch)

        # 3) 失败批次逐条重试
        for batch in failed_batches:
            if self.cancel.is_set():
                break
            for t in batch:
                if self.cancel.is_set():
                    break
                try:
                    lines = _call_batch([t], self.cfg)
                    results[t] = lines[0]
                    done += 1
                    self.progress.emit(done, total, t)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{t[:60]}… : {exc}")

        if self.cache is not None:
            self.cache.merge(results)
        self.finished.emit(results, errors)
