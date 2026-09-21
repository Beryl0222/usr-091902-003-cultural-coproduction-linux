"""首部作品《丝路·流沙记》多地上线端到端走查。

直接运行：python3 scenario.py
覆盖：文化边界返工、地区权利矩阵、素材发放隔离、跨时区重复交付、
工时锁定、发行闸门、收益依据固化、撤权阻断与波及分析。
"""

import json

from domain import CoproductionApp, DomainError, Store
from domain.seed import load_first_title

IP = "ip-silkroad"


def show(title, payload):
    print(f"\n{'─' * 68}\n{title}\n{'─' * 68}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def prep_version(app, proposal, region, asset_ids, resolved, rating, hours,
                 editor=None, parent=None, delivery_key=None, at=None):
    """把一个市场版本推到"可发行"：素材、本地化限定处置、三审、工时、交付。"""
    version = app.open_version(proposal, editor=editor or f"剪辑-{region}",
                               parent_id=parent)
    for aid in asset_ids:
        app.attach_asset(version["id"], aid, purpose="正片使用")
    app.adapt_region(version["id"], region,
                     note=f"{region} 本地化：字幕/配音与合规删改",
                     resolved_restrictions=resolved)
    app.translation_review(version["id"], region, f"译审-{region}", "通过",
                           note="译文与口型已核对")
    app.culture_review(version["id"], region, f"文化复核-{region}", "通过")
    app.rate_region(version["id"], region, f"分级机构-{region}", rating)
    app.log_work(version["id"], hours, note=f"{region} 版本制作工时")
    app.settle_work(version["id"])
    if delivery_key:
        app.deliver(version["id"], region, idem_key=delivery_key,
                    package_ref=f"pkg-{region}-final", at=at)
    return version


def main():
    app = CoproductionApp(Store())
    load_first_title(app.store)

    # ── 1. 四个市场的改编提案 ──────────────────────────────────────
    app.create_proposal("prop-th", IP, "team-bkk", "泰语本地化短剧版", target_regions=["TH"])
    app.create_proposal("prop-id", IP, "team-jkt", "印尼语本地化短剧版", target_regions=["ID"])
    app.create_proposal("prop-me", IP, "team-dxb", "海湾地区阿语改编版", target_regions=["AE"])
    app.add_proposal_elements("prop-th", ["ce-mural"])
    app.add_proposal_elements("prop-id", ["ce-mural"])
    app.add_proposal_elements("prop-me", ["ce-mural", "ce-prayer"])
    app.culture_decide("prop-th", "敦煌研究院联络人", "通过", note="壁画使用符合限定")
    app.culture_decide("prop-id", "敦煌研究院联络人", "通过")
    app.culture_decide("prop-me", "中东文化顾问团", "通过",
                       note="礼拜桥段须改写并逐版复核")
    # ── 2. 泰国首版误用未确认音乐，发行闸门拦截 ────────────────────
    v1 = app.open_version("prop-th", editor="剪辑-TH", note="首剪")
    for aid in ("as-bgm", "as-lead", "as-art", "as-folk"):
        app.attach_asset(v1["id"], aid, purpose="正片使用")
    app.adapt_region(v1["id"], "TH", note="泰语字幕与配音",
                     resolved_restrictions=["cr-mural-01"])
    app.translation_review(v1["id"], "TH", "译审-TH", "通过")
    app.culture_review(v1["id"], "TH", "文化复核-TH", "通过")
    app.rate_region(v1["id"], "TH", "分级机构-TH", "PG-13（泰国）")
    app.log_work(v1["id"], 120, note="首版制作")
    app.settle_work(v1["id"])

    bad_plan = app.plan_release(IP, "TH", v1["id"], channel="流媒体",
                                scheduled="2026-06-01", rid="rp-th-v1")["计划"]
    blocked = app.gate_checks(bad_plan)
    show("① 泰国首版发行闸门（民间乐曲采样未确认 → 阻塞）",
         [c for c in blocked if c["状态"] != "通过"])
    try:
        app.approve_release("rp-th-v1")
        raise AssertionError("未确认音乐的版本不应被放行")
    except DomainError as exc:
        print(f"\n放行被拒：{exc}")
    app.cancel_release("rp-th-v1", reason="返工去未确认采样后重提")

    # ── 3. 返工开 v2：已核算工时不可改写 ──────────────────────────
    v2 = app.open_version("prop-th", editor="剪辑-TH", parent_id=v1["id"],
                          note="去除未确认民间采样")
    for aid in ("as-bgm", "as-lead", "as-art"):
        app.attach_asset(v2["id"], aid, purpose="正片使用")
    app.adapt_region(v2["id"], "TH", note="泰语字幕与配音（沿用）",
                     resolved_restrictions=["cr-mural-01"])
    app.translation_review(v2["id"], "TH", "译审-TH", "通过")
    app.culture_review(v2["id"], "TH", "文化复核-TH", "通过")
    app.rate_region(v2["id"], "TH", "分级机构-TH", "PG-13（泰国）")
    app.log_work(v2["id"], 25, note="返工增量工时")
    app.settle_work(v2["id"])
    try:
        app.log_work(v1["id"], 10, note="试图把返工工时塞进旧版本")
        raise AssertionError("已核算工时不应再被改写")
    except DomainError as exc:
        print(f"\n② 旧版工时改写被拒：{exc}")
    st1 = app.store.get("work_settlement", f"st-{v1['id']}")
    st2 = app.store.get("work_settlement", f"st-{v2['id']}")
    show("② 工时台账：v1=120 锁定不变，v2=25 单独核算",
         {"v1": {"总工时": st1["总工时"], "锁定": st1["锁定"]},
          "v2": {"总工时": st2["总工时"], "锁定": st2["锁定"]},
          "谱系": app.lineage("prop-th")})
    app.abandon_version(v1["id"], reason="v2 返工定稿")

    # ── 4. 跨时区重复交付只入账一次 ────────────────────────────────
    first = app.deliver(v2["id"], "TH", idem_key="TH-v2-20260531",
                        package_ref="pkg-th-final",
                        at="2026-05-31T16:30:00+00:00")
    second = app.deliver(v2["id"], "TH", idem_key="TH-v2-20260531",
                         package_ref="pkg-th-final",
                         at="2026-05-31T23:30:00+07:00")  # 同一时刻曼谷本地重发
    third = app.deliver(v2["id"], "TH", idem_key="TH-v2-20260531",
                        package_ref="pkg-th-final",
                        at="2026-06-01T08:00:00+09:00")   # 东京同事次日再点一次
    deliveries = app.store.query("delivery", 版本=v2["id"])
    show("③ 三次提交（UTC / 曼谷 / 东京）只入账一条",
         {"首次是否重复": first["是否重复"], "末次是否重复": second["是否重复"] or third["是否重复"],
          "入账条数": len(deliveries), "入账交付": deliveries[0]["id"],
          "入账时间(UTC)": deliveries[0]["交付时间"]})

    # ── 5. 素材发放：境外团队只领取对应地区所需 ────────────────────
    pkg_th = app.grant_material("team-bkk", "TH")
    pkg_ae = app.grant_material("team-dxb", "AE")
    show("④ 分地区素材包（泰包无中东肖像，阿包无泰国肖像；未确认采样不出现）",
         {"泰国包": pkg_th["素材"], "阿联酋包": pkg_ae["素材"]})
    for desc, kwargs in [
        ("曼谷团队领 AE 素材", {"team_id": "team-bkk", "region": "AE",
                              "asset_ids": ["as-lead-me"]}),
        ("把未确认采样发往境外", {"team_id": "team-bkk", "region": "TH",
                                 "asset_ids": ["as-folk"]}),
        ("把泰国肖像发往 AE", {"team_id": "team-dxb", "region": "AE",
                              "asset_ids": ["as-lead"]}),
    ]:
        try:
            app.grant_material(**kwargs)
            raise AssertionError(desc + " 不应成功")
        except DomainError as exc:
            print(f"⑤ 素材发放拦截｜{desc}：{exc}")

    # ── 6. 泰国放行、上线，收益依据固化 ────────────────────────────
    rp_th = app.plan_release(IP, "TH", v2["id"], channel="流媒体",
                             scheduled="2026-06-01", idem_key="plan-th-20260601",
                             rid="rp-th")["计划"]
    app.approve_release("rp-th")
    app.go_live("rp-th", at="2026-06-01T12:00:00+07:00")
    show("⑥ 泰国副本已上线，放行时固化收益分配依据",
         {"状态": rp_th["状态"], "闸门": [c["名称"] for c in rp_th["闸门"]],
          "收益依据": rp_th["收益依据"]})

    # ── 7. 阿联酋：文化限定未处置时先被拦，补齐后上线 ──────────────
    v_ae = app.open_version("prop-me", editor="剪辑-AE")
    for aid in ("as-bgm", "as-lead-me", "as-art"):
        app.attach_asset(v_ae["id"], aid, purpose="正片使用")
    app.adapt_region(v_ae["id"], "AE", note="阿语配音，初版仅处理壁画限定",
                     resolved_restrictions=["cr-mural-01"])
    app.translation_review(v_ae["id"], "AE", "译审-AE", "通过")
    app.culture_review(v_ae["id"], "AE", "文化复核-AE", "通过")
    app.rate_region(v_ae["id"], "AE", "分级机构-AE", "PG-15（阿联酋）")
    app.log_work(v_ae["id"], 140, note="阿语版制作")
    app.settle_work(v_ae["id"])
    app.deliver(v_ae["id"], "AE", idem_key="AE-v1-20260701",
                package_ref="pkg-ae-final", at="2026-07-01T08:00:00Z")
    rp_ae = app.plan_release(IP, "AE", v_ae["id"], channel="流媒体",
                             scheduled="2026-07-15", rid="rp-ae")["计划"]
    pending = [c for c in app.gate_checks(rp_ae) if c["状态"] != "通过"]
    show("⑦ 阿联酋初检：礼拜桥段改写限定尚未处置", pending)
    app.adapt_region(v_ae["id"], "AE", note="礼拜桥段已改写为中性仪式",
                     resolved_restrictions=["cr-mural-01", "cr-prayer-me"])
    app.culture_review(v_ae["id"], "AE", "文化复核-AE", "通过",
                       note="改写后复核通过")
    app.approve_release("rp-ae")
    app.go_live("rp-ae", at="2026-07-15T16:00:00+04:00")

    # ── 8. 印尼：万事俱备、只待上线的待核验计划（撤权时应被精确阻断）──
    v_id = app.open_version("prop-id", editor="剪辑-ID")
    for aid in ("as-bgm", "as-lead", "as-art"):
        app.attach_asset(v_id["id"], aid, purpose="正片使用")
    app.adapt_region(v_id["id"], "ID", note="印尼语字幕与配音",
                     resolved_restrictions=["cr-mural-01"])
    app.translation_review(v_id["id"], "ID", "译审-ID", "通过")
    app.culture_review(v_id["id"], "ID", "文化复核-ID", "通过")
    app.rate_region(v_id["id"], "ID", "分级机构-ID", "SU（印尼，全年龄）")
    app.log_work(v_id["id"], 110, note="印尼版制作")
    app.settle_work(v_id["id"])
    app.deliver(v_id["id"], "ID", idem_key="ID-v1-20260830",
                package_ref="pkg-id-final", at="2026-08-30T09:00:00Z")
    rp_id = app.plan_release(IP, "ID", v_id["id"], channel="流媒体",
                             scheduled="2026-09-01", rid="rp-id")["计划"]
    assert all(c["状态"] == "通过" for c in app.gate_checks(rp_id)), \
        "撤权前印尼计划闸门应全部通过"

    # ── 9. 版权方撤回东南亚授权：精确阻断 + 波及清单 ──────────────
    impact = app.withdrawal_impact("lic-sea")
    show("⑧ 撤权前影响分析（只涉及 TH/ID，不波及 AE）",
         {"阻断未发布": [p["id"] for p in impact["阻断未发布"]],
          "波及副本": [{"计划": p["id"], "渠道": p["渠道"]} for p in impact["波及副本"]],
          "受影响渠道": impact["受影响渠道"]})
    result = app.revoke_license("lic-sea", reason="版权方战略调整，终止东南亚授权")
    show("⑨ 执行撤回：未发布即阻断，已上线副本标记等待下线",
         {"授权状态": result["授权"]["状态"],
          "泰国副本": {"状态": rp_th["状态"], "撤权波及": rp_th["撤权波及"]},
          "印尼计划": {"状态": rp_id["状态"],
                     "阻塞项": [c["名称"] for c in rp_id["闸门"] if c["状态"] != "通过"]},
          "阿联酋副本": {"状态": rp_ae["状态"], "撤权波及": rp_ae["撤权波及"]}})
    app.takedown("rp-th", reason="授权撤回，执行下线")

    # ── 10. 管理看板 ───────────────────────────────────────────────
    overview = app.market_overview(IP)
    show("⑩ 管理看板：各市场成片 / 未决阻塞 / 收益依据 / 撤权波及", overview)

    # ── 汇总断言 ───────────────────────────────────────────────────
    assert st1["总工时"] == 120.0 and st2["总工时"] == 25.0
    assert len(deliveries) == 1
    assert set(pkg_th["素材"]) == {"as-bgm", "as-lead", "as-art"}
    assert set(pkg_ae["素材"]) == {"as-bgm", "as-lead-me", "as-art"}
    assert rp_id["状态"] == "已阻断" and rp_th["状态"] == "已下线"
    assert rp_ae["状态"] == "已上线" and rp_ae["撤权波及"] is False
    assert rp_th["收益依据"]["版权方分成比例"] == 0.55
    assert rp_ae["收益依据"]["版权方分成比例"] == 0.60
    print("\n全部场景断言通过 ✔")


if __name__ == "__main__":
    main()
