"""跨文化内容共制：版本关系、地区权利与发行闸门的核心规则。

设计要点：
- 版本关系：原始 IP → 改编提案 → 成片版本（返工形成父子谱系）→ 分市场发行副本；
- 权利矩阵：授权按"地区 × 期限 × 渠道"覆盖；素材（含演员、音乐）单独确认且只覆盖部分地区；
- 发行闸门：放行前同时核验地区权利、素材确认与地区覆盖、文化限定处置、
  文化复核、译审意见、当地分级、工时核算七项；
- 工时核算后锁定，返工只能开新版本，不能改写台账；
- 交付以幂等键去重，跨时区重复提交只入账一次；
- 授权撤回立即阻断未发布计划，并列出每个受波及的已上线副本与渠道。
"""

import uuid
from datetime import date

from . import records as R
from .errors import ConflictError, GateBlockedError, NotFoundError, ValidationError


def _parse_day(value):
    """把 YYYY-MM-DD 或 ISO 时间戳统一折成 date 做期限比较。"""
    if value is None:
        raise ValidationError("缺少日期")
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"无法解析日期：{value}") from exc


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class CoproductionApp:
    def __init__(self, store):
        self.store = store

    # ── 主数据：IP、团队、素材、文化元素 ───────────────────────────

    def register_ip(self, rid, title, *, kind, rights_holder, summary=""):
        return self.store.add(R.ip_work(rid, title, kind=kind,
                                        rights_holder=rights_holder, summary=summary))

    def register_team(self, rid, name, *, regions, timezone):
        return self.store.add(R.team(rid, name, regions=regions, timezone=timezone))

    def register_asset(self, rid, ip_id, name, *, kind, owner, confirmed, regions=None):
        self.store.get("ip", ip_id)
        return self.store.add(R.asset(rid, ip_id, name, kind=kind, owner=owner,
                                      confirmed=confirmed, regions=regions))

    def confirm_asset(self, asset_id, *, note="", regions=None):
        """确认演员/音乐等成分的使用权；可顺带补齐覆盖地区。"""
        asset = self.store.get("asset", asset_id)
        asset["已确认"] = True
        if regions is not None:
            asset["覆盖地区"] = sorted(set(asset["覆盖地区"]) | set(regions))
        asset["确认备注"] = note or asset["确认备注"]
        self.store.log("asset_confirmed", 素材=asset_id, 覆盖地区=asset["覆盖地区"])
        return asset

    def register_culture_element(self, rid, ip_id, name, *, sensitivity="普通"):
        self.store.get("ip", ip_id)
        return self.store.add(R.culture_element(rid, ip_id, name, sensitivity=sensitivity))

    def add_restriction(self, element_id, advisor, rule, *, regions=None, rid=None):
        """文化顾问对敏感元素限定使用方式；regions 为空表示适用于全部地区。"""
        element = self.store.get("culture_element", element_id)
        rec = R.culture_restriction(rid or _new_id("cr"), element_id, advisor, rule,
                                    regions=regions)
        self.store.add(rec)
        element["限定"].append(rec["id"])
        self.store.log("restriction_added", 元素=element_id, 限定=rec["id"],
                       适用地区=rec["适用地区"])
        return rec

    # ── 授权矩阵 ───────────────────────────────────────────────────

    def grant_license(self, rid, ip_id, holder, *, regions, start, end,
                      exclusive=False, channels=None, revenue_share=0.0):
        self.store.get("ip", ip_id)
        if _parse_day(end) < _parse_day(start):
            raise ValidationError("授权结束日不得早于开始日")
        rec = R.license_grant(rid, ip_id, holder, regions=regions, start=start, end=end,
                              exclusive=exclusive, channels=channels,
                              revenue_share=revenue_share)
        self.store.add(rec)
        self.store.log("license_granted", 授权=rid, IP=ip_id,
                       地区=rec["授权地区"], 渠道=rec["渠道"])
        return rec

    def revoke_license(self, grant_id, *, reason=""):
        """撤回授权：阻断所有未发布计划，标记已上线副本等待下线，并给出影响面。"""
        grant = self.store.get("license_grant", grant_id)
        if grant["状态"] != "生效":
            raise ConflictError(f"授权 {grant_id} 已非生效状态", details={"授权": grant_id})
        impact = self.withdrawal_impact(grant_id)
        grant["状态"] = "已撤回"
        grant["撤回时间"] = R.now_iso()
        grant["撤回原因"] = reason

        blocked, affected = [], []
        for plan in impact["阻断未发布"]:
            plan["状态"] = "已阻断"
            plan["闸门"] = self.gate_checks(plan)
            blocked.append(plan["id"])
        for plan in impact["波及副本"]:
            # 已上线副本不能凭空消失：标记撤权波及，由发行方执行下线处置
            plan["撤权波及"] = True
            affected.append({"副本": plan["id"], "渠道": plan["渠道"],
                             "上线时间": plan["上线时间"]})

        self.store.log("license_revoked", 授权=grant_id, 原因=reason,
                       地区=grant["授权地区"], 阻断计划=blocked, 波及副本=affected)
        return {"授权": grant, "影响": impact}

    def _covering_license(self, ip_id, region, channel, day):
        """返回覆盖 地区/渠道/日期 的生效授权；同地区重复生效授权取期限最新者。"""
        candidates = []
        for grant in self.store.query("license_grant", 所属IP=ip_id, 状态="生效"):
            if region not in grant["授权地区"]:
                continue
            if channel not in grant["渠道"]:
                continue
            if not (grant["开始"] <= day.isoformat() <= grant["结束"]):
                continue
            candidates.append(grant)
        if not candidates:
            return None
        return sorted(candidates, key=lambda g: g["结束"], reverse=True)[0]

    def withdrawal_impact(self, grant_id):
        """撤权影响分析：准确指出被阻断的未发布版本与受影响渠道/副本。"""
        grant = self.store.get("license_grant", grant_id)
        regions = set(grant["授权地区"])
        blocked, affected = [], []
        for plan in self.store.list("release_plan"):
            if plan["所属IP"] != grant["所属IP"]:
                continue
            if plan["地区"] not in regions:
                continue
            if plan["状态"] in ("待核验", "已放行"):
                blocked.append(plan)
            elif plan["状态"] == "已上线":
                affected.append(plan)
        return {
            "授权": grant_id,
            "版权方": grant["版权方"],
            "地区": sorted(regions),
            "阻断未发布": blocked,
            "波及副本": affected,
            "受影响渠道": sorted({p["渠道"] for p in blocked + affected}),
        }

    # ── 改编提案与文化决议 ─────────────────────────────────────────

    def create_proposal(self, rid, ip_id, team_id, summary, *, target_regions):
        self.store.get("ip", ip_id)
        self.store.get("team", team_id)
        missing = set(target_regions) - set(self.store.get("team", team_id)["负责地区"])
        if missing:
            raise ValidationError(
                "团队不负责这些目标地区", details={"地区": sorted(missing)})
        return self.store.add(R.proposal(rid, ip_id, team_id, summary,
                                         target_regions=target_regions))

    def add_proposal_elements(self, proposal_id, element_ids):
        proposal = self.store.get("proposal", proposal_id)
        for eid in element_ids:
            element = self.store.get("culture_element", eid)
            if element["所属IP"] != proposal["所属IP"]:
                raise ValidationError("文化元素不属于该提案的 IP", details={"元素": eid})
        proposal["涉及元素"] = sorted(set(proposal["涉及元素"]) | set(element_ids))
        return proposal

    def culture_decide(self, proposal_id, advisor, verdict, *, note=""):
        if verdict not in ("通过", "需修改", "驳回"):
            raise ValidationError("文化决议结论无效", details={"结论": verdict})
        proposal = self.store.get("proposal", proposal_id)
        rec = R.culture_decision(_new_id("cd"), proposal_id, advisor, verdict, note=note)
        self.store.add(rec)
        proposal["文化决议"].append(rec["id"])
        proposal["文化状态"] = verdict
        self.store.log("culture_decided", 提案=proposal_id, 结论=verdict, 顾问=advisor)
        return rec

    # ── 成片版本与返工谱系 ─────────────────────────────────────────

    def open_version(self, proposal_id, *, editor, note="", parent_id=None, rid=None):
        """开新版成片；parent_id 非空表示返工版本，谱系由此连成链。"""
        proposal = self.store.get("proposal", proposal_id)
        seq = 1
        if parent_id is not None:
            parent = self.store.get("cut_version", parent_id)
            if parent["提案"] != proposal_id:
                raise ValidationError("父版本不属于该提案")
            # 父版本工时即使已核算也可作为返工起点；
            # 旧台账保持不变，新工时只记在新版本上（见 log_work）
            seq = parent["版本序号"] + 1
        else:
            existing = self.store.query("cut_version", 提案=proposal_id)
            if existing:
                raise ConflictError("首版已存在，返工须指定父版本",
                                    details={"提案": proposal_id})
        ver = R.cut_version(rid or _new_id("v"), proposal_id, parent_id, seq,
                            editor=editor, note=note)
        self.store.add(ver)
        self.store.log("version_opened", 版本=ver["id"], 提案=proposal_id,
                       序号=seq, 父版本=parent_id)
        return ver

    def _version_ip(self, version):
        proposal = self.store.get("proposal", version["提案"])
        return proposal, self.store.get("ip", proposal["所属IP"])

    def abandon_version(self, version_id, *, reason=""):
        """返工定稿后，废弃旧版本；已核算工时仍保留在台账中。"""
        version = self.store.get("cut_version", version_id)
        version["废弃"] = True
        self.store.log("version_abandoned", 版本=version_id, 原因=reason)
        return version

    def attach_asset(self, version_id, asset_id, *, purpose=""):
        version = self.store.get("cut_version", version_id)
        proposal, ip_work = self._version_ip(version)
        asset = self.store.get("asset", asset_id)
        if asset["所属IP"] != ip_work["id"]:
            raise ValidationError("素材不属于该版本的 IP", details={"素材": asset_id})
        if any(item["素材"] == asset_id for item in version["素材"]):
            raise ConflictError("素材已挂接该版本", details={"素材": asset_id})
        version["素材"].append({"素材": asset_id, "用途": purpose})
        return version

    def adapt_region(self, version_id, region, *, note, resolved_restrictions=None):
        """登记某地区本地化方案，并声明已处置的文化限定。"""
        version = self.store.get("cut_version", version_id)
        resolved = sorted(set(resolved_restrictions or []))
        known = {rid for eid in self.store.get("proposal", version["提案"])["涉及元素"]
                 for rid in self.store.get("culture_element", eid)["限定"]}
        unknown = set(resolved) - known
        if unknown:
            raise ValidationError("处置的限定与本提案无关", details={"限定": sorted(unknown)})
        version["地区适配"][region] = {"说明": note, "已处置限定": resolved}
        return version

    # ── 译审 / 分级 / 文化复核 ─────────────────────────────────────

    def translation_review(self, version_id, region, reviewer, verdict, *, note=""):
        if verdict not in ("通过", "退回"):
            raise ValidationError("译审结论只能是 通过/退回")
        return self._record_review(version_id, region, reviewer,
                                   f"译审{verdict}", note=note,
                                   state_field="译审", state=verdict)

    def rate_region(self, version_id, region, reviewer, rating, *, note=""):
        if not rating:
            raise ValidationError("分级结论不能为空")
        return self._record_review(version_id, region, reviewer, "分级",
                                   note=note, rating=rating,
                                   state_field="分级", state=rating)

    def culture_review(self, version_id, region, reviewer, verdict, *, note=""):
        if verdict not in ("通过", "退回"):
            raise ValidationError("文化复核结论只能是 通过/退回")
        return self._record_review(version_id, region, reviewer,
                                   f"文化复核{verdict}", note=note,
                                   state_field="文化复核", state=verdict)

    def _record_review(self, version_id, region, reviewer, verdict, *, note,
                       rating=None, state_field, state):
        version = self.store.get("cut_version", version_id)
        rec = R.review_note(_new_id("rv"), version_id, region, reviewer, verdict,
                            note=note, rating=rating)
        self.store.add(rec)
        version[state_field][region] = state
        version["复核记录"].append(rec["id"])
        return rec

    # ── 工时台账（核算后锁定）──────────────────────────────────────

    def log_work(self, version_id, hours, *, note="", at=None, rid=None):
        version = self.store.get("cut_version", version_id)
        if version["工时已核算"]:
            raise ConflictError(
                "该版本工时已核算并锁定，返工不得改写；请在新版本上记录工时",
                details={"版本": version_id})
        proposal = self.store.get("proposal", version["提案"])
        rec = R.work_log(rid or _new_id("w"), version_id, proposal["制片团队"],
                         hours, note=note, at=at)
        self.store.add(rec)
        return rec

    def settle_work(self, version_id):
        """核算某版本工时；核算后台账与版本均锁定。"""
        version = self.store.get("cut_version", version_id)
        if version["工时已核算"]:
            raise ConflictError("该版本工时已核算", details={"版本": version_id})
        logs = [w for w in self.store.query("work_log", 版本=version_id)
                if w["核算状态"] == "待核算"]
        if not logs:
            raise ValidationError("没有待核算的工时", details={"版本": version_id})
        total = sum(w["工时"] for w in logs)
        for w in logs:
            w["核算状态"] = "已核算"
            w["核算时间"] = R.now_iso()
        settlement = R.work_settlement(version_id, total, [w["id"] for w in logs])
        self.store.add(settlement, replace=True)
        version["工时已核算"] = True
        self.store.log("work_settled", 版本=version_id, 总工时=total,
                       台账=[w["id"] for w in logs])
        return settlement

    # ── 素材发放：只领取对应地区所需 ───────────────────────────────

    def grant_material(self, team_id, region, *, asset_ids=None, package_ref=None,
                       ip_id=None, rid=None):
        team = self.store.get("team", team_id)
        if region not in team["负责地区"]:
            raise ValidationError("团队不负责该地区，不能领取该地区素材",
                                  details={"地区": region})
        if asset_ids is None:
            # 自动打包：指定作品时只收该作品下的素材；
            # 未指定时默认取该团队已承接提案涉及的作品，避免跨作品泄露
            if ip_id is not None:
                ip_ids = {ip_id}
            else:
                ip_ids = {self.store.get("proposal", p["id"])["所属IP"]
                          for p in self.store.query("proposal", 制片团队=team_id)}
            if not ip_ids:
                raise ValidationError(
                    "无法确定打包范围：请指定作品 IP，或先建立改编提案",
                    details={"团队": team_id})
            asset_ids = [a["id"] for a in self.store.list("asset")
                         if a["所属IP"] in ip_ids
                         and a["已确认"] and region in a["覆盖地区"]]
        for aid in asset_ids:
            asset = self.store.get("asset", aid)
            if not asset["已确认"]:
                raise ConflictError("素材尚未确认，不能发往境外团队",
                                    details={"素材": aid})
            if region not in asset["覆盖地区"]:
                raise ConflictError("素材权利不覆盖该地区，禁止发放",
                                    details={"素材": aid, "地区": region,
                                             "覆盖地区": asset["覆盖地区"]})
        rec = R.material_grant(rid or _new_id("mg"), team_id, region, asset_ids,
                               package_ref=package_ref or f"pkg-{region}-{uuid.uuid4().hex[:6]}")
        self.store.add(rec)
        self.store.log("material_granted", 团队=team_id, 地区=region, 素材=asset_ids)
        return rec

    # ── 交付：跨时区幂等入账 ───────────────────────────────────────

    def deliver(self, version_id, region, *, idem_key, package_ref, at):
        """登记交付。同一 idem_key 在任一时区重提都只返回首次入账记录。

        记录 ID 由幂等键确定性派生（dlv-<idem_key>），
        即使两个请求并发、跨时区重提，命中的也是同一条入账。
        """
        version = self.store.get("cut_version", version_id)
        proposal = self.store.get("proposal", version["提案"])
        delivery_id = f"dlv-{idem_key}"
        existing = self.store.find("delivery", delivery_id)
        if existing is not None:
            self.store.log("delivery_deduplicated", 幂等键=idem_key,
                           入账交付=existing["id"], 重复提交时间=at)
            return {"交付": existing, "是否重复": True}
        _parse_day(at)  # 时间必须可解析，统一按 UTC 事件时间入账
        rec = R.delivery(delivery_id, version_id, proposal["制片团队"], region,
                         idem_key, package_ref=package_ref, at=at)
        self.store.add(rec)
        self.store.log("delivery_booked", 交付=rec["id"], 幂等键=idem_key,
                       版本=version_id, 地区=region, 交付时间=at)
        return {"交付": rec, "是否重复": False}

    # ── 发行计划与闸门 ─────────────────────────────────────────────

    def plan_release(self, ip_id, region, version_id, *, channel, scheduled,
                     idem_key=None, rid=None):
        ip_work = self.store.get("ip", ip_id)
        version = self.store.get("cut_version", version_id)
        proposal = self.store.get("proposal", version["提案"])
        if proposal["所属IP"] != ip_work["id"]:
            raise ValidationError("成片版本不属于该 IP")
        if region not in proposal["目标地区"]:
            raise ValidationError("该地区不在改编提案目标范围内", details={"地区": region})
        if idem_key:
            dup = next((p for p in self.store.query("release_plan", 所属IP=ip_id)
                        if p.get("幂等键") == idem_key), None)
            if dup:
                return {"计划": dup, "是否重复": True}
        plan = R.release_plan(rid or _new_id("rp"), ip_id, region, version_id,
                              channel=channel, scheduled=scheduled, idem_key=idem_key)
        self.store.add(plan)
        self.store.log("release_planned", 计划=plan["id"], IP=ip_id,
                       地区=region, 版本=version_id, 渠道=channel)
        return {"计划": plan, "是否重复": False}

    def _applicable_restrictions(self, version, region):
        proposal = self.store.get("proposal", version["提案"])
        out = []
        for eid in proposal["涉及元素"]:
            element = self.store.get("culture_element", eid)
            for crid in element["限定"]:
                cr = self.store.get("culture_restriction", crid)
                if not cr["生效"]:
                    continue
                if not cr["适用地区"] or region in cr["适用地区"]:
                    out.append(cr)
        return out

    def gate_checks(self, plan):
        """发行前七项核验，返回逐项结果；任何一项不通过都构成未决阻塞。"""
        ip_work = self.store.get("ip", plan["所属IP"])
        version = self.store.get("cut_version", plan["成片版本"])
        region, channel = plan["地区"], plan["渠道"]
        day = _parse_day(plan["计划上线"])
        checks = []

        # 0) 版本有效性：已废弃版本不能发行
        checks.append({
            "名称": "版本有效性",
            "状态": "阻塞" if version["废弃"] else "通过",
            "明细": "版本已废弃，返工后请改用新版本" if version["废弃"]
                    else f"v{version['版本序号']} 有效"})

        # 1) 地区权利：地区 × 渠道 × 期限
        grant = self._covering_license(ip_work["id"], region, channel, day)
        if grant:
            checks.append({"名称": "地区权利", "状态": "通过",
                           "明细": f"授权 {grant['id']}（{grant['开始']}~{grant['结束']}，"
                                   f"{'独家' if grant['独家'] else '非独家'}）"})
        else:
            checks.append({"名称": "地区权利", "状态": "阻塞",
                           "明细": f"{region}/{channel} 在 {day} 无生效授权覆盖"})

        # 2) 素材确认与地区覆盖（演员、音乐等）
        unconfirmed, uncovered = [], []
        for item in version["素材"]:
            asset = self.store.get("asset", item["素材"])
            if not asset["已确认"]:
                unconfirmed.append(asset["名称"])
            elif region not in asset["覆盖地区"]:
                uncovered.append(f"{asset['名称']}（仅覆盖 {'、'.join(asset['覆盖地区'])}）")
        detail = []
        if unconfirmed:
            detail.append(f"尚未确认：{'、'.join(unconfirmed)}")
        if uncovered:
            detail.append(f"权利不覆盖{region}：{'、'.join(uncovered)}")
        checks.append({"名称": "素材确认与地区覆盖", "状态": "阻塞" if detail else "通过",
                       "明细": "；".join(detail) or f"共 {len(version['素材'])} 项素材均已确认且覆盖该地区"})

        # 3) 文化限定处置
        restrictions = self._applicable_restrictions(version, region)
        resolved = set(version["地区适配"].get(region, {}).get("已处置限定", []))
        pending_cr = [cr for cr in restrictions if cr["id"] not in resolved]
        checks.append({
            "名称": "文化限定处置",
            "状态": "阻塞" if pending_cr else "通过",
            "明细": "；".join(f"{cr['顾问']}:{cr['限定要求']}" for cr in pending_cr)
                    or f"已处置 {len(restrictions)} 条适用限定"})

        # 4) 文化复核
        cv = version["文化复核"].get(region)
        checks.append({"名称": "文化复核", "状态": "通过" if cv == "通过" else "阻塞",
                       "明细": f"复核结论：{cv or '未提交'}"})

        # 5) 译审意见
        tr = version["译审"].get(region)
        checks.append({"名称": "译审意见", "状态": "通过" if tr == "通过" else "阻塞",
                       "明细": f"译审结论：{tr or '未提交'}"})

        # 6) 当地分级
        rating = version["分级"].get(region)
        checks.append({"名称": "当地分级", "状态": "通过" if rating else "阻塞",
                       "明细": f"分级：{rating or '未取得'}"})

        # 7) 工时核算（收益分配依据）
        settlement = self.store.find("work_settlement", f"st-{version['id']}")
        checks.append({
            "名称": "工时核算",
            "状态": "通过" if version["工时已核算"] and settlement else "阻塞",
            "明细": f"已核算总工时 {settlement['总工时']}" if settlement else "工时尚未核算"})

        return checks

    def approve_release(self, plan_id):
        """七项闸门全部通过才放行，并固化收益分配依据快照。"""
        plan = self.store.get("release_plan", plan_id)
        if plan["状态"] in ("已上线", "已阻断", "已撤回", "已下线"):
            raise ConflictError(f"计划状态为 {plan['状态']}，不能放行",
                                details={"计划": plan_id, "状态": plan["状态"]})
        checks = self.gate_checks(plan)
        plan["闸门"] = checks
        failed = [c for c in checks if c["状态"] != "通过"]
        if failed:
            raise GateBlockedError(plan_id, checks)

        day = _parse_day(plan["计划上线"])
        grant = self._covering_license(plan["所属IP"], plan["地区"], plan["渠道"], day)
        settlement = self.store.find("work_settlement", f"st-{plan['成片版本']}")
        plan["收益依据"] = {
            "授权": grant["id"],
            "版权方": grant["版权方"],
            "地区": plan["地区"],
            "渠道": plan["渠道"],
            "版权方分成比例": grant["分成比例"],
            "成片版本": plan["成片版本"],
            "核算总工时": settlement["总工时"],
            "工时台账": settlement["台账明细"],
            "固化时间": R.now_iso(),
        }
        plan["状态"] = "已放行"
        plan["放行时间"] = R.now_iso()
        self.store.log("release_approved", 计划=plan_id, 地区=plan["地区"],
                       渠道=plan["渠道"], 授权=grant["id"])
        return plan

    def go_live(self, plan_id, *, at=None):
        plan = self.store.get("release_plan", plan_id)
        if plan["状态"] != "已放行":
            raise ConflictError("只有已放行计划可以上线",
                                details={"计划": plan_id, "状态": plan["状态"]})
        plan["状态"] = "已上线"
        plan["上线时间"] = at or R.now_iso()
        self.store.log("gone_live", 计划=plan_id, 地区=plan["地区"],
                       渠道=plan["渠道"], 上线时间=plan["上线时间"])
        return plan

    def cancel_release(self, plan_id, *, reason=""):
        """放行前撤销发行计划（如返工换版）；已放行/已上线需走阻断或下线。"""
        plan = self.store.get("release_plan", plan_id)
        if plan["状态"] != "待核验":
            raise ConflictError("只有待核验计划可以取消",
                                details={"计划": plan_id, "状态": plan["状态"]})
        plan["状态"] = "已取消"
        self.store.log("release_cancelled", 计划=plan_id, 原因=reason)
        return plan

    def takedown(self, plan_id, *, reason=""):
        """撤权波及副本的下线处置。"""
        plan = self.store.get("release_plan", plan_id)
        if plan["状态"] != "已上线":
            raise ConflictError("只有已上线副本可以下线",
                                details={"计划": plan_id, "状态": plan["状态"]})
        plan["状态"] = "已下线"
        plan["撤权波及"] = False
        self.store.log("taken_down", 计划=plan_id, 原因=reason, 地区=plan["地区"])
        return plan

    # ── 查询：版本谱系与管理看板 ───────────────────────────────────

    def lineage(self, proposal_id):
        self.store.get("proposal", proposal_id)
        versions = sorted(self.store.query("cut_version", 提案=proposal_id),
                          key=lambda v: v["版本序号"])
        return [{"版本": v["id"], "序号": v["版本序号"], "父版本": v["父版本"],
                 "工时已核算": v["工时已核算"], "素材": [i["素材"] for i in v["素材"]],
                 "地区": sorted(set(v["译审"]) | set(v["分级"]) | set(v["文化复核"]))}
                for v in versions]

    def market_overview(self, ip_id):
        """管理人员视图：各市场所用成片、未决阻塞、收益依据与撤权波及副本。"""
        ip_work = self.store.get("ip", ip_id)
        markets = {}
        for plan in sorted(self.store.query("release_plan", 所属IP=ip_id),
                           key=lambda p: (p["地区"], p["渠道"])):
            entry = markets.setdefault(plan["地区"], {
                "地区": plan["地区"], "成片版本": plan["成片版本"], "发行副本": [],
                "未决阻塞": [], "收益依据": [], "撤权波及副本": []})
            entry["成片版本"] = plan["成片版本"]
            checks = plan.get("闸门") or (self.gate_checks(plan)
                                          if plan["状态"] == "待核验" else [])
            pending = [c["名称"] for c in checks if c["状态"] != "通过"]
            entry["发行副本"].append({
                "计划": plan["id"], "渠道": plan["渠道"], "成片版本": plan["成片版本"],
                "状态": plan["状态"],
                "计划上线": plan["计划上线"], "上线时间": plan["上线时间"]})
            if pending and plan["状态"] in ("待核验", "已阻断"):
                entry["未决阻塞"].extend(f"{plan['渠道']}:{name}" for name in pending)
            if plan["收益依据"]:
                entry["收益依据"].append({"渠道": plan["渠道"], **plan["收益依据"]})
            if plan["撤权波及"]:
                entry["撤权波及副本"].append({"计划": plan["id"], "渠道": plan["渠道"],
                                              "上线时间": plan["上线时间"]})
        return {
            "作品": {"id": ip_work["id"], "名称": ip_work["名称"]},
            "市场": sorted(markets.values(), key=lambda m: m["地区"]),
        }
