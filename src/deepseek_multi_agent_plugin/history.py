# -*- coding: utf-8 -*-
"""运行历史持久化（RunHistory）。

以 JSONL 追加方式把每次协作任务（run）的摘要记录写入文件，支持读取最近
N 条、清空与条数统计。仅使用 Python 标准库；追加与读取共用一把锁，
多线程并发追加不会丢记录。
"""
import json
import os
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List


class RunHistory:
    """线程安全的 JSONL 运行历史存储。

    文件不存在时自动创建（含父目录）；重新打开同一文件会延续已有的
    自增序号。
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = Lock()
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(path):
            # 历史记录含提示词与结果，新文件以 0600 创建，避免同机其他用户可读。
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.close(fd)
        self._count = self._count_lines()

    def _count_lines(self) -> int:
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """补充 timestamp（ISO 8601 本地时间）与自增 index 后追加一行
        JSON，返回写后的完整记录。"""
        with self._lock:
            self._count += 1
            item = dict(record)
            item["index"] = self._count
            item["timestamp"] = datetime.now().isoformat(timespec="seconds")
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            return item

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """读取最近 limit 条记录（倒序，最新在前）。

        从文件尾部按块向前扫描，凑齐 limit 条有效记录（或扫到文件头）即停，
        避免大历史文件全量读取。以二进制方式打开并用 errors="replace" 解码，
        损坏行（非 JSON）依旧跳过；返回语义与旧实现完全一致。
        """
        with self._lock:
            limit = max(0, int(limit))
            if limit == 0:
                return []
            items: List[Dict[str, Any]] = []
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                pos = f.tell()
                if pos == 0:
                    return []
                chunk = b""  # 尚未拆分出完整行的尾部字节缓冲
                block_size = 4096
                while pos > 0 and len(items) < limit:
                    read_size = min(block_size, pos)
                    pos -= read_size
                    f.seek(pos)
                    chunk = f.read(read_size) + chunk
                    parts = chunk.split(b"\n")
                    if pos > 0:
                        # 尚未到达文件头：块首可能是不完整的行，留给下一轮拼接
                        chunk = parts[0]
                        parts = parts[1:]
                    else:
                        # 已到达文件头：剩余字节都是完整内容（含末尾无换行的行）
                        chunk = b""
                    # 块内行按逆序处理，保证最新记录在最前
                    for raw in reversed(parts):
                        if not raw.strip():
                            continue
                        try:
                            items.append(json.loads(raw.decode("utf-8", errors="replace")))
                        except ValueError:
                            continue  # 跳过损坏行
                        if len(items) >= limit:
                            break
        return items

    def clear(self) -> None:
        """清空历史文件并重置序号。"""
        with self._lock:
            with open(self.path, "w", encoding="utf-8"):
                pass
            self._count = 0

    def __len__(self) -> int:
        with self._lock:
            return self._count
