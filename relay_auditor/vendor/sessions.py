"""Read-only, allowlisted Codex rollout accounting (no message text retained).

Modern response usage is authoritative. Legacy cumulative snapshots are differenced
and used only for turns without modern records. Cache/reasoning are subsets, never
added a second time. Session ownership is *creator* evidence, not a billing claim.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from .safety import checked_local_path

TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens", "total_tokens")


def _text(value: object, limit: int = 1000) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    result = {}
    for key in TOKEN_FIELDS:
        item = value.get(key, 0)
        if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item) or item < 0:
            return None
        result[key] = int(item)
    if not any(key in value for key in ("input_tokens", "output_tokens", "total_tokens")):
        return None
    if "total_tokens" not in value:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


def _zeros() -> dict[str, int]:
    return dict.fromkeys(TOKEN_FIELDS, 0)


def _add(target: dict, values: dict) -> None:
    for key in TOKEN_FIELDS:
        target[key] = target.get(key, 0) + values.get(key, 0)


def _source(path: Path, line: int | None = None) -> dict:
    result = {"path": str(path), "uri": path.as_uri(), "kind": "session",
              "description": "Codex 本地会话记录；仅提取计数、模型、推理强度及归属元数据。", "exists": True}
    if line is not None:
        result["line"] = line
    return result


def _walk(root: Path, warnings: list[str]):
    try:
        root = checked_local_path(root)
        if not root.exists():
            return
        for directory, dirs, files in os.walk(root, followlinks=False):
            safe_dirs = []
            for name in dirs:
                try:
                    checked_local_path(Path(directory)/name)
                    safe_dirs.append(name)
                except (OSError, ValueError):
                    warnings.append(f"跳过链接或非本地目录：{Path(directory)/name}")
            dirs[:] = safe_dirs
            for name in files:
                if name.endswith(".jsonl"):
                    try:
                        yield checked_local_path(Path(directory)/name)
                    except (OSError, ValueError):
                        warnings.append(f"跳过链接或非本地文件：{Path(directory)/name}")
    except (OSError, ValueError) as exc:
        warnings.append(f"会话目录不可读取：{root}（{type(exc).__name__}）")


def _rows(path: Path, coverage: Counter, warnings: list[str]):
    try:
        # Capture size before opening: a running Codex may append during the scan.
        # Never consume a line extending beyond this per-file snapshot boundary.
        path = checked_local_path(path)
        size = path.stat().st_size
        consumed = 0
        with path.open("rb") as stream:
            for line_no, raw in enumerate(stream, 1):
                consumed += len(raw)
                if consumed > size:
                    coverage["lines_appended_during_scan"] += 1
                    break
                coverage["lines_read"] += 1
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeError):
                    coverage["malformed_lines"] += 1
                    continue
                if isinstance(row, dict) and isinstance(row.get("payload"), dict):
                    yield line_no, row
        coverage["files_read"] += 1
        coverage["bytes_read"] += min(consumed, size)
    except (OSError, ValueError) as exc:
        coverage["unreadable_files"] += 1
        warnings.append(f"文件不可读取：{path}（{type(exc).__name__}）")


def _limits(value: object) -> list[dict]:
    """Only documented scalar/window fields survive; arbitrary nested data does not."""
    if isinstance(value, list):
        return [item for v in value for item in _limits(v)]
    if not isinstance(value, dict):
        return []
    if not any(k in value for k in ("primary", "secondary", "limit_id", "credits")):
        # Some builds expose a map keyed by bucket id.
        return [dict(item, limit_id=item.get("limit_id") or str(k)[:100])
                for k, v in value.items() if isinstance(v, dict) for item in _limits(v)]
    result = {k: _text(value.get(k), 200) for k in ("limit_id", "limit_name", "plan_type", "rate_limit_reached_type")}
    for key in ("primary", "secondary"):
        window = value.get(key)
        result[key] = None
        if isinstance(window, dict):
            clean = {}
            for field in ("used_percent", "window_minutes", "resets_at"):
                number = window.get(field)
                clean[field] = number if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and number >= 0 else None
            if any(v is not None for v in clean.values()):
                result[key] = clean
    credits = value.get("credits")
    result["credits"] = None
    if isinstance(credits, dict):
        result["credits"] = {k: credits[k] if isinstance(credits.get(k), bool) else None for k in ("has_credits", "unlimited")}
        balance = credits.get("balance")
        if isinstance(balance, (str, int, float)) and not isinstance(balance, bool):
            try:
                numeric = float(balance)
                result["credits"]["balance"] = str(balance)[:50] if math.isfinite(numeric) else None
            except ValueError:
                result["credits"]["balance"] = None
    reached = value.get("spend_control_reached")
    result["spend_control_reached"] = reached if isinstance(reached, bool) else None
    individual = value.get("individual_limit")
    if isinstance(individual, (bool, int, float)):
        result["individual_limit"] = individual
    return [result]


def scan_sessions(codex_home: Path, *, current_account_id: str | None = None) -> dict[str, Any]:
    home = checked_local_path(codex_home)
    warnings: list[str] = []
    coverage: Counter = Counter()
    sources: list[dict] = []
    titles: dict[str, str] = {}
    index = home/"session_index.jsonl"
    try:
        index = checked_local_path(index)
        if index.is_file():
            sources.append(dict(_source(index), kind="session_index", description="本地会话名称索引，不读取对话正文。"))
            with index.open(encoding="utf-8-sig") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict) and _text(row.get("id")) and _text(row.get("thread_name")):
                            titles[row["id"]] = row["thread_name"][:500]
                    except (ValueError, UnicodeError):
                        coverage["malformed_index_lines"] += 1
    except (OSError, ValueError) as exc:
        warnings.append(f"会话名称索引不可读取：{index}（{type(exc).__name__}）")

    paths = sorted(set(_walk(home/"sessions", warnings) or ()) | set(_walk(home/"archived_sessions", warnings) or ()))
    coverage["files_discovered"] = len(paths)
    sessions: dict[str, dict] = {}
    turns: dict[tuple[str, str], dict] = {}
    modern: dict[tuple, dict] = {}
    legacy: list[dict] = []
    limits: list[dict] = []
    snapshots: set[tuple] = set()
    counter_state: dict[str, dict] = {}
    legacy_seen: set[tuple] = set()

    def get_session(sid: str, path: Path, meta: dict | None = None) -> dict:
        meta = meta or {}
        account = _text(meta.get("creator_account_id") or meta.get("account_id"))
        if sid not in sessions:
            sessions[sid] = {
                "id": sid, "title": titles.get(sid) or f"会话 {sid[:12]}",
                "project": _text(meta.get("cwd")) or "未记录项目", "created_at": _text(meta.get("timestamp")),
                "updated_at": None, "model": None, "reasoning_effort": None,
                "source": _source(path, 1), "sources": [], "creator_account_id": account,
                "root_session_id": _text(meta.get("session_id")) or sid,
                "root_session_id_recorded": bool(_text(meta.get("session_id"))),
                "parent_thread_id": _text(meta.get("parent_thread_id") or meta.get("forked_from_id")),
                "thread_source": _text(meta.get("thread_source")) or "unknown",
                "model_provider": _text(meta.get("model_provider")), "cli_version": _text(meta.get("cli_version")),
                "attribution": "unknown", "attribution_basis": "unavailable", "turn_count": 0, **_zeros(),
            }
        session = sessions[sid]
        if account:
            session["creator_account_id"] = account
            session["attribution"] = "matched" if current_account_id and account == current_account_id else "other" if current_account_id else "unknown"
            session["attribution_basis"] = "session_creator_account_id"
        if _text(meta.get("cwd")):
            session["project"] = meta["cwd"][:1000]
        if str(path) not in session["sources"]:
            session["sources"].append(str(path))
        return session

    def get_turn(sid: str, tid: str, path: Path, line: int, timestamp: str | None) -> dict:
        key = (sid, tid)
        if key not in turns:
            session = get_session(sid, path)
            turns[key] = {"id": tid, "session_id": sid, "title": session["title"], "project": session["project"],
                          "started_at": timestamp, "ended_at": None, "model": None, "reasoning_effort": None,
                          "root_turn_id": tid, "status": "incomplete", "source": _source(path, line),
                          "root_turn_id_recorded": False,
                          "attribution": session["attribution"], "attribution_basis": session["attribution_basis"],
                          "model_segments": [], "request_count": 0, "usage_record_count": 0,
                          "accounting_method": None, **_zeros()}
        return turns[key]

    for path in paths:
        sources.append(_source(path))
        sid = "file-" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        current_tid: str | None = None
        current_model: str | None = None
        current_effort: str | None = None
        explicit_turn = False
        has_usage = False
        first_meta = False
        history_end = 0
        for line_no, row in _rows(path, coverage, warnings):
            kind, payload = row.get("type"), row["payload"]
            timestamp = _text(row.get("timestamp"), 100)
            subtype = payload.get("type")
            if kind == "session_meta":
                if not first_meta:
                    first_meta = True
                    sid = _text(payload.get("id") or payload.get("session_id")) or sid
                    get_session(sid, path, payload)
                    ordinal = payload.get("subagent_history_start_ordinal")
                    history_end = ordinal if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0 else 0
                # Later session_meta is inherited parent history, never overwrite identity.
                continue
            if history_end and line_no <= history_end:
                coverage["inherited_history_lines_skipped"] += 1
                continue
            session = get_session(sid, path)
            if timestamp and (not session["updated_at"] or timestamp > session["updated_at"]):
                session["updated_at"] = timestamp
            if kind == "turn_context" or (kind == "event_msg" and subtype == "task_started"):
                explicit_id = _text(payload.get("turn_id"))
                if explicit_id:
                    new_tid = explicit_id
                elif current_tid and (not has_usage or explicit_turn):
                    new_tid = current_tid
                else:
                    new_tid = "inferred-" + hashlib.sha256(f"{sid}|{timestamp}|{line_no}".encode()).hexdigest()[:16]
                if current_tid != new_tid:
                    current_tid, has_usage = new_tid, False
                turn = get_turn(sid, current_tid, path, line_no, _text(payload.get("started_at")) or timestamp)
                if subtype == "task_started":
                    explicit_turn = True
                    turn["started_at"] = _text(payload.get("started_at")) or timestamp or turn["started_at"]
                if _text(payload.get("root_turn_id")):
                    turn["root_turn_id"] = payload["root_turn_id"]
                    turn["root_turn_id_recorded"] = True
                if kind == "turn_context":
                    current_model = _text(payload.get("model")) or current_model
                    current_effort = _text(payload.get("effort") or payload.get("reasoning_effort")) or current_effort
                    turn["model"] = current_model
                    turn["reasoning_effort"] = current_effort
                    if _text(payload.get("cwd")):
                        turn["project"] = payload["cwd"][:1000]
                continue
            if kind == "event_msg" and subtype == "user_message" and not explicit_turn:
                if not current_tid or has_usage:
                    current_tid = "inferred-" + hashlib.sha256(f"{sid}|{timestamp}|{line_no}".encode()).hexdigest()[:16]
                    get_turn(sid, current_tid, path, line_no, timestamp)
                    has_usage = False
                continue
            if kind == "event_msg" and subtype in ("task_complete", "turn_aborted"):
                tid = _text(payload.get("turn_id")) or current_tid
                if tid:
                    turn = get_turn(sid, tid, path, line_no, timestamp)
                    turn["ended_at"] = _text(payload.get("completed_at")) or timestamp
                    turn["status"] = "completed" if subtype == "task_complete" else "aborted"
                current_tid, explicit_turn, has_usage = None, False, False
                continue
            if kind == "token_usage_record":
                values = _usage(payload.get("usage"))
                if values is None:
                    coverage["invalid_usage_records"] += 1
                    continue
                usage_sid = _text(payload.get("thread_id")) or sid
                tid = _text(payload.get("turn_id")) or current_tid or "unassigned"
                turn = get_turn(usage_sid, tid, path, line_no, timestamp)
                if _text(payload.get("root_turn_id")):
                    turn["root_turn_id"] = payload["root_turn_id"]
                    turn["root_turn_id_recorded"] = True
                response_id = _text(payload.get("response_id"))
                dedup = ("response", response_id) if response_id else ("record", usage_sid, tid, timestamp, tuple(values.values()))
                item = {"sid": usage_sid, "tid": tid, "timestamp": timestamp, "model": current_model,
                        "reasoning_effort": current_effort, "source": _source(path, line_no), "values": values,
                        "method": "response_usage", "response_id": response_id}
                if dedup in modern:
                    coverage["duplicate_response_records"] += 1
                    if modern[dedup]["values"] != values:
                        coverage["conflicting_response_records"] += 1
                else:
                    modern[dedup] = item
                current_tid, has_usage = tid if usage_sid == sid else current_tid, True
                continue
            if kind != "event_msg" or subtype != "token_count":
                continue
            for limit in _limits(payload.get("rate_limits")):
                limit.update(timestamp=timestamp, source=_source(path, line_no), session_id=sid,
                             attribution=session["attribution"], account_id=session["creator_account_id"],
                             attribution_basis=session["attribution_basis"], model=current_model)
                # Identical stored snapshots at the same instant are a single observation.
                signature = (sid, timestamp, json.dumps(limit, sort_keys=True, ensure_ascii=False))
                if signature not in snapshots:
                    snapshots.add(signature)
                    limits.append(limit)
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            total, last = _usage(info.get("total_token_usage")), _usage(info.get("last_token_usage"))
            if total is None:
                # last_token_usage alone cannot be reliably distinguished from a replay.
                coverage["snapshots_without_cumulative_usage"] += 1
                continue
            tid = current_tid or "unassigned"
            previous = counter_state.get(sid)
            family = sid
            ancestors = set()
            while family in sessions and family not in ancestors and sessions[family].get("parent_thread_id"):
                ancestors.add(family)
                family = sessions[family]["parent_thread_id"]
            fingerprint = (family, tid, timestamp, tuple(total.values()))
            if fingerprint in legacy_seen:
                coverage["duplicate_snapshots"] += 1
                continue
            legacy_seen.add(fingerprint)
            values = None
            if previous is not None and total == previous:
                coverage["unchanged_snapshots"] += 1
            elif previous is not None and all(total[k] >= previous[k] for k in TOKEN_FIELDS):
                values = {k: total[k] - previous[k] for k in TOKEN_FIELDS}
            else:
                if previous is not None:
                    coverage["counter_resets_or_replays"] += 1
                # A first snapshot or a reset can include earlier history. Only the
                # reported last response is safe to count, never the whole baseline.
                if last is not None and all(last[k] <= total[k] for k in TOKEN_FIELDS):
                    values = last
                    if total["total_tokens"] > last["total_tokens"]:
                        coverage["baseline_snapshots_with_prior_usage"] += 1
                else:
                    coverage["unallocated_initial_snapshots"] += 1
            counter_state[sid] = total
            if values and any(values.values()):
                get_turn(sid, tid, path, line_no, timestamp)
                legacy.append({"sid": sid, "tid": tid, "timestamp": timestamp, "model": current_model,
                               "reasoning_effort": current_effort, "source": _source(path, line_no),
                               "values": values, "method": "cumulative_delta"})
                has_usage = True

    modern_turns = {(v["sid"], v["tid"]) for v in modern.values()}
    modern_totals: Counter = Counter()
    legacy_totals: Counter = Counter()
    for item in modern.values():
        modern_totals[(item["sid"], item["tid"])] += item["values"]["total_tokens"]
    for item in legacy:
        legacy_totals[(item["sid"], item["tid"])] += item["values"]["total_tokens"]
    coverage["modern_records_below_legacy_deltas"] = sum(legacy_totals[key] > modern_totals[key] for key in modern_turns)
    selected = list(modern.values())
    for item in legacy:
        if (item["sid"], item["tid"]) in modern_turns:
            coverage["legacy_snapshots_superseded"] += 1
        else:
            selected.append(item)
    selected.sort(key=lambda item: (item["timestamp"] or "", item["source"]["path"], item["source"]["line"]))
    for item in selected:
        turn = turns[(item["sid"], item["tid"])]
        _add(turn, item["values"])
        turn["usage_record_count"] += 1
        turn["request_count"] += int(item["method"] == "response_usage")
        turn["accounting_method"] = item["method"]
        segments = turn["model_segments"]
        segment = next((v for v in segments if (v["model"], v["reasoning_effort"]) == (item["model"], item["reasoning_effort"])), None)
        if segment is None:
            segment = {"model": item["model"], "reasoning_effort": item["reasoning_effort"], "request_count": 0, **_zeros()}
            segments.append(segment)
        _add(segment, item["values"])
        segment["request_count"] += int(item["method"] == "response_usage")
        if "usage_sources" not in turn:
            turn["usage_sources"] = []
        turn["usage_sources"].append(item["source"])
    for (sid, _tid), turn in turns.items():
        session = sessions[sid]
        turn["attribution"] = session["attribution"]
        turn["attribution_basis"] = session["attribution_basis"]
        turn["creator_account_id"] = session["creator_account_id"]
        turn["root_session_id"] = session["root_session_id"]
        turn["thread_source"] = session["thread_source"]
        turn["is_subagent"] = session["thread_source"] == "subagent" or session["root_session_id"] != sid
        turn["title"] = session["title"]
        models = {x["model"] for x in turn["model_segments"]}
        efforts = {x["reasoning_effort"] for x in turn["model_segments"]}
        if models:
            turn["model"] = next(iter(models)) if len(models) == 1 else "mixed"
        if efforts:
            turn["reasoning_effort"] = next(iter(efforts)) if len(efforts) == 1 else "mixed"
        _add(session, turn)
        session["turn_count"] += 1
    for sid, session in sessions.items():
        group = [turn for (s, _), turn in turns.items() if s == sid]
        for key in ("model", "reasoning_effort"):
            choices = {t[key] for t in group if t[key]}
            session[key] = next(iter(choices)) if len(choices) == 1 else "mixed" if choices else None
        session["request_count"] = sum(t["request_count"] for t in group)
        session["usage_record_count"] = sum(t["usage_record_count"] for t in group)
        session["is_subagent"] = session["thread_source"] == "subagent" or session["root_session_id"] != sid
        session["inclusive_tokens"] = {k: session[k] for k in TOKEN_FIELDS}
        session["child_session_count"] = 0
    # Inclusive views are presentation-only: direct fields remain the additive base.
    # A child is joined using explicit root IDs, never timestamps or token guesses.
    for turn in turns.values():
        turn["inclusive_tokens"] = {k: turn[k] for k in TOKEN_FIELDS}
        turn["child_turn_count"] = 0
    for (sid, tid), turn in turns.items():
        if not turn["is_subagent"]:
            continue
        root_key = (turn["root_session_id"], turn["root_turn_id"])
        root = turns.get(root_key)
        if root_key != (sid, tid) and root and turn["root_turn_id_recorded"] and sessions[sid]["root_session_id_recorded"]:
            _add(root["inclusive_tokens"], turn)
            root["child_turn_count"] += 1
        else:
            coverage["subagent_turns_without_verified_root_turn"] += 1
    for sid, session in sessions.items():
        if not session["is_subagent"]:
            continue
        root_id = session["root_session_id"]
        root = sessions.get(root_id)
        if root_id != sid and root and session["root_session_id_recorded"]:
            _add(root["inclusive_tokens"], session)
            root["child_session_count"] += 1
        else:
            coverage["subagent_sessions_without_verified_root_session"] += 1
    coverage["modern_response_count"] = len(modern)
    coverage["legacy_usage_delta_count"] = len(selected) - len(modern)
    coverage["sessions_with_creator_account"] = sum(bool(s["creator_account_id"]) for s in sessions.values())
    coverage["sessions_without_creator_account"] = len(sessions) - coverage["sessions_with_creator_account"]
    coverage["turns_without_usage"] = sum(t["usage_record_count"] == 0 for t in turns.values())
    if coverage["malformed_lines"]:
        warnings.append(f"跳过 {coverage['malformed_lines']} 行不完整或无效 JSON；活动会话可能尚未写完。")
    if coverage["unallocated_initial_snapshots"] or coverage["baseline_snapshots_with_prior_usage"]:
        warnings.append("部分累计快照含既有历史；优先逐响应记录，旧格式仅计可确认的增量，不把继承的累计值重复加入。")
    if coverage["counter_resets_or_replays"]:
        warnings.append("检测到累计计数回退或重放；旧格式从最后一条可确认响应重新建立基线。")
    if coverage["conflicting_response_records"]:
        warnings.append("相同响应 ID 出现不同计数，保留第一次记录并将其标为数据冲突。")
    if coverage["modern_records_below_legacy_deltas"]:
        warnings.append("部分轮次的逐响应记录小于旧累计增量；为避免重复统计，采用可核验的逐响应记录，该部分可能不完整。")
    if coverage["subagent_turns_without_verified_root_turn"]:
        warnings.append("部分子代理轮次缺少可验证的根轮次关联；仍计入本地总量，但未猜测归入某次用户问答。")
    warnings.append("归属依据为会话创建账号；同会话切换登录后，无法仅凭该字段确认每次调用的计费账号。")
    warnings.append("本地记录不涵盖已删除、未同步、其他设备或服务端未落盘的用量；限额仅为记录时的快照。")
    return {"turns": sorted(turns.values(), key=lambda t: (t["started_at"] or "", t["id"]), reverse=True),
            "sessions": sorted(sessions.values(), key=lambda s: (s["updated_at"] or "", s["id"]), reverse=True),
            "rate_limits": sorted(limits, key=lambda x: x["timestamp"] or "", reverse=True),
            "sources": sources, "warnings": warnings, "coverage": dict(coverage)}
