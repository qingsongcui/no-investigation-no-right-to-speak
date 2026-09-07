#!/usr/bin/env python3
"""journal.py — 基于哈希流水账的调用级断点续跑与回放工具（对标 Grok journal.rs）

用途：
1. 为每个子代理调用（如 collector、red_team、gate）计算规范化请求的 SHA256 哈希指纹；
2. 在调查目录下维护 .journal.jsonl 流水账；
3. 重跑或恢复时，若输入指纹匹配且结果有效，毫秒级直接回放输出，跳过网络调用；
4. 仅在指纹不匹配或无缓存时触发实际调用。

命令行接口：
  python3 tools/journal.py record <inv_dir> <task_type> <input_json_or_file> <output_json_or_file>
  python3 tools/journal.py query <inv_dir> <task_type> <input_json_or_file>
  python3 tools/journal.py list <inv_dir>
  python3 tools/journal.py clear <inv_dir>
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def canonical_hash(task_type: str, payload: Any) -> str:
    """计算任务类型与输入载荷的规范化 SHA256 哈希指纹（前 32 位）。"""
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            norm_str = json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        except Exception:
            norm_str = payload.strip()
    else:
        norm_str = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    
    hasher = hashlib.sha256()
    hasher.update(task_type.strip().encode('utf-8'))
    hasher.update(b':')
    hasher.update(norm_str.encode('utf-8'))
    return hasher.hexdigest()[:32]


def get_journal_path(inv_dir: Path) -> Path:
    return inv_dir / ".journal.jsonl"


def load_entries(inv_dir: Path) -> List[Dict[str, Any]]:
    jpath = get_journal_path(inv_dir)
    if not jpath.exists():
        return []
    entries = []
    for line in jpath.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return entries


def record(inv_dir: Path, task_type: str, input_payload: Any, output_payload: Any) -> Dict[str, Any]:
    """记录一条调用结果至流水账。"""
    jpath = get_journal_path(inv_dir)
    entries = load_entries(inv_dir)
    input_hash = canonical_hash(task_type, input_payload)
    seq = len(entries) + 1
    
    entry = {
        "seq": seq,
        "timestamp": datetime.now().isoformat(),
        "task_type": task_type,
        "input_hash": input_hash,
        "input": input_payload if not isinstance(input_payload, str) else _try_parse_json(input_payload),
        "output": output_payload if not isinstance(output_payload, str) else _try_parse_json(output_payload)
    }
    
    with open(jpath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def query(inv_dir: Path, task_type: str, input_payload: Any) -> Optional[Dict[str, Any]]:
    """查询是否存在匹配的已完成调用。若存在返回最新的一条记录，否则返回 None。"""
    entries = load_entries(inv_dir)
    if not entries:
        return None
    target_hash = canonical_hash(task_type, input_payload)
    for entry in reversed(entries):
        if entry.get("task_type") == task_type and entry.get("input_hash") == target_hash:
            return entry
    return None


def clear(inv_dir: Path) -> bool:
    jpath = get_journal_path(inv_dir)
    if jpath.exists():
        jpath.unlink()
        return True
    return False


def _try_parse_json(val: str) -> Any:
    try:
        return json.loads(val)
    except Exception:
        return val


def _load_arg_payload(arg: str) -> Any:
    p = Path(arg)
    if p.exists() and p.is_file():
        text = p.read_text(encoding='utf-8')
        return _try_parse_json(text)
    return _try_parse_json(arg)


def main():
    parser = argparse.ArgumentParser(description="基于哈希流水账的调用级断点续跑工具")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # record
    p_rec = subparsers.add_parser("record", help="记录调用流水账")
    p_rec.add_argument("inv_dir", type=str, help="调查目录")
    p_rec.add_argument("task_type", type=str, help="任务类型 (collector/red_team/gate)")
    p_rec.add_argument("input_data", type=str, help="输入内容或JSON文件路径")
    p_rec.add_argument("output_data", type=str, help="输出内容或JSON文件路径")

    # query
    p_q = subparsers.add_parser("query", help="查询调用缓存")
    p_q.add_argument("inv_dir", type=str, help="调查目录")
    p_q.add_argument("task_type", type=str, help="任务类型")
    p_q.add_argument("input_data", type=str, help="输入内容或JSON文件路径")

    # list
    p_l = subparsers.add_parser("list", help="列出流水账记录")
    p_l.add_argument("inv_dir", type=str, help="调查目录")

    # clear
    p_c = subparsers.add_parser("clear", help="清空流水账")
    p_c.add_argument("inv_dir", type=str, help="调查目录")

    args = parser.parse_args()
    inv_dir = Path(args.inv_dir)
    if not inv_dir.exists():
        print(f"[FAIL] 调查目录不存在: {inv_dir}", file=sys.stderr)
        return 1

    if args.cmd == "record":
        in_payload = _load_arg_payload(args.input_data)
        out_payload = _load_arg_payload(args.output_data)
        entry = record(inv_dir, args.task_type, in_payload, out_payload)
        print(f"[OK] 已记录 seq={entry['seq']} hash={entry['input_hash']}")
        return 0

    elif args.cmd == "query":
        in_payload = _load_arg_payload(args.input_data)
        entry = query(inv_dir, args.task_type, in_payload)
        if entry is not None:
            print(json.dumps(entry.get("output"), ensure_ascii=False, indent=2))
            return 0
        else:
            return 1

    elif args.cmd == "list":
        entries = load_entries(inv_dir)
        print(f"调查目录: {inv_dir.name} | 流水账记录共 {len(entries)} 条")
        for e in entries:
            print(f"  #{e['seq']} [{e['timestamp'][:19]}] {e['task_type']} -> {e['input_hash']}")
        return 0

    elif args.cmd == "clear":
        cleared = clear(inv_dir)
        print(f"[OK] 已清空流水账: {inv_dir}" if cleared else "[INFO] 无流水账文件")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
