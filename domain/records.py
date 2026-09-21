"""领域记录定义。

所有记录使用普通 dict 存放，集中在此处给出字段结构与构造函数，
保证业务记录"由正式接口产生"（见 fixtures/domain.json 的说明）。
"""

from datetime import datetime, timezone


def now_iso():
    """统一的时间戳口径：UTC ISO8601（跨时区比较的基准）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(kind, rid, **fields):
    data = {"id": rid, "类型": kind, "创建时间": now_iso()}
    data.update(fields)
    return data


# ── 原始 IP ─────────────────────────────────────────────────────────

def ip_work(rid, title, *, kind, rights_holder, summary=""):
    return record(
        "ip",
        rid,
        名称=title,
        作品类别=kind,          # 游戏 | 短剧 | 小说 ...
        原始版权方=rights_holder,
        简介=summary,
    )


# ── 素材（含演员、音乐等需逐项确认权利的成分）──────────────────────

def asset(rid, ip_id, name, *, kind, owner, confirmed, regions=None):
    return record(
        "asset",
        rid,
        所属IP=ip_id,
        名称=name,
        素材类别=kind,          # 画面 | 音乐 | 演员形象 | 剧本 ...
        权利方=owner,
        已确认=bool(confirmed),  # 演员/音乐等在成片中使用前必须确认
        覆盖地区=sorted(regions or []),
        确认备注="",
    )


# ── 文化元素与顾问限定 ─────────────────────────────────────────────

def culture_element(rid, ip_id, name, *, sensitivity="普通"):
    return record(
        "culture_element",
        rid,
        所属IP=ip_id,
        名称=name,
        敏感级别=sensitivity,   # 普通 | 需关注 | 敏感
        限定=[],                # 文化顾问给出的使用限定，见 culture_restriction
    )


def culture_restriction(rid, element_id, advisor, rule, *, regions=None, active=True):
    return record(
        "culture_restriction",
        rid,
        元素=element_id,
        顾问=advisor,
        限定要求=rule,
        适用地区=sorted(regions or []),   # 空表示全部地区
        生效=active,
    )


# ── 授权（地区 × 期限的权利矩阵条目）───────────────────────────────

def license_grant(rid, ip_id, holder, *, regions, start, end, exclusive=False,
                  status="生效", channels=None, revenue_share=0.0):
    return record(
        "license_grant",
        rid,
        所属IP=ip_id,
        版权方=holder,
        授权地区=sorted(regions),
        开始=start,
        结束=end,               # 期限：发行日必须落在区间内
        独家=exclusive,
        渠道=sorted(channels or ["流媒体"]),
        状态=status,            # 生效 | 已撤回
        分成比例=float(revenue_share),  # 版权方收益分成（发行放行时固化）
        撤回时间=None,
        撤回原因="",
    )


# ── 境外制片团队 ───────────────────────────────────────────────────

def team(rid, name, *, regions, timezone):
    return record(
        "team",
        rid,
        名称=name,
        负责地区=sorted(regions),
        时区=timezone,          # 如 "UTC+7"，交付统一折算 UTC 入账
    )


# ── 改编提案与文化决议 ─────────────────────────────────────────────

def proposal(rid, ip_id, team_id, summary, *, target_regions):
    return record(
        "proposal",
        rid,
        所属IP=ip_id,
        制片团队=team_id,
        改编概述=summary,
        目标地区=sorted(target_regions),
        涉及元素=[],
        文化状态="待审",         # 待审 | 通过 | 需修改 | 驳回
        文化决议=[],
    )


def culture_decision(drid, proposal_id, advisor, verdict, *, note="", at=None):
    return record(
        "culture_decision",
        drid,
        提案=proposal_id,
        顾问=advisor,
        结论=verdict,           # 通过 | 需修改 | 驳回
        意见=note,
        时间=at or now_iso(),
    )


# ── 制片版本（返工形成谱系）────────────────────────────────────────

def cut_version(rid, proposal_id, parent_id, seq, *, editor, note=""):
    return record(
        "cut_version",
        rid,
        提案=proposal_id,
        父版本=parent_id,        # None 为首版；返工版本指向父版本
        版本序号=seq,
        剪辑负责人=editor,
        说明=note,
        素材=[],                 # [{"素材": asset_id, "用途": ...}]
        地区适配={},             # region -> 本地化说明（字幕/配音/删改）
        译审={},                 # region -> 待译审 | 通过 | 退回
        分级={},                 # region -> 分级结论（如 PG-13）
        文化复核={},             # region -> 待复核 | 通过 | 退回
        复核记录=[],
        工时已核算=False,
        废弃=False,
    )


def review_note(rid, version_id, region, reviewer, verdict, *, note="", rating=None):
    return record(
        "review_note",
        rid,
        版本=version_id,
        地区=region,
        审校人=reviewer,
        结论=verdict,           # 译审通过 | 译审退回 | 分级 | 文化复核通过 | 文化复核退回
        分级=rating,
        意见=note,
        时间=now_iso(),
    )


# ── 工时台账（核算后不可改写）──────────────────────────────────────

def work_log(rid, version_id, team_id, hours, *, note="", at=None):
    return record(
        "work_log",
        rid,
        版本=version_id,
        团队=team_id,
        工时=float(hours),
        说明=note,
        提交时间=at or now_iso(),
        核算状态="待核算",
        核算时间=None,
    )


def work_settlement(version_id, total_hours, logs, at=None):
    return record(
        "work_settlement",
        f"st-{version_id}",
        版本=version_id,
        总工时=float(total_hours),
        台账明细=list(logs),
        核算时间=at or now_iso(),
        锁定=True,
    )


# ── 素材发放（境外团队只领取对应地区所需）──────────────────────────

def material_grant(rid, team_id, region, asset_ids, *, package_ref):
    return record(
        "material_grant",
        rid,
        团队=team_id,
        地区=region,
        素材=list(asset_ids),
        包引用=package_ref,
        发放时间=now_iso(),
    )


# ── 交付（跨时区重复交付只入账一次）────────────────────────────────

def delivery(rid, version_id, team_id, region, idem_key, *, package_ref, at):
    return record(
        "delivery",
        rid,
        版本=version_id,
        团队=team_id,
        地区=region,
        幂等键=idem_key,         # 同一交付物在任一时区重提均命中
        包引用=package_ref,
        交付时间=at,             # 以事件携带的 UTC 时间入账
        入账状态="已入账",
    )


# ── 发行计划与副本（每个"市场 × 成片"是一个副本）──────────────────

def release_plan(rid, ip_id, region, version_id, *, channel, scheduled, idem_key=None):
    return record(
        "release_plan",
        rid,
        所属IP=ip_id,
        地区=region,
        成片版本=version_id,
        渠道=channel,
        计划上线=scheduled,
        状态="待核验",           # 待核验 | 已放行 | 已上线 | 已阻断 | 已撤回 | 已下线
        闸门=[],
        放行时间=None,
        上线时间=None,
        幂等键=idem_key,
        收益依据=None,           # 放行时固化的分配依据快照
        撤权波及=False,           # 授权撤回时：已上线副本被标记，等待下线处置
    )
