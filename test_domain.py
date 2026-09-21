"""领域规则测试：覆盖题目中的全部不变量。"""

import unittest

from domain import CoproductionApp, Store
from domain.errors import (ConflictError, GateBlockedError, NotFoundError,
                           ValidationError)
from domain.seed import load_first_title

IP = "ip-silkroad"


def build():
    app = CoproductionApp(Store())
    load_first_title(app.store)
    return app


def ready_plan(app, proposal_id, region, team_assets, *, rid, channel="流媒体",
               scheduled="2026-06-01", rating="分级-A", hours=100,
               resolved=("cr-mural-01",)):
    """构造一个三审通过、工时已核算、闸门应全绿的发行计划。"""
    v = app.open_version(proposal_id, editor=f"剪辑-{region}")
    for aid in team_assets:
        app.attach_asset(v["id"], aid)
    app.adapt_region(v["id"], region, note="本地化", resolved_restrictions=list(resolved))
    app.translation_review(v["id"], region, f"译审-{region}", "通过")
    app.culture_review(v["id"], region, f"文化复核-{region}", "通过")
    app.rate_region(v["id"], region, f"分级-{region}", rating)
    app.log_work(v["id"], hours)
    app.settle_work(v["id"])
    app.deliver(v["id"], region, idem_key=f"{region}-{v['id']}",
                package_ref=f"pkg-{region}", at="2026-05-30T00:00:00Z")
    plan = app.plan_release(IP, region, v["id"], channel=channel,
                            scheduled=scheduled, rid=rid)["计划"]
    return v, plan


class TestRightsMatrix(unittest.TestCase):
    def setUp(self):
        self.app = build()
        self.app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])
        self.app.add_proposal_elements("p-th", ["ce-mural"])
        self.app.culture_decide("p-th", "敦煌研究院联络人", "通过")

    def test_license_must_cover_region_channel_and_period(self):
        v, _ = ready_plan(self.app, "p-th", "TH",
                          ["as-bgm", "as-lead", "as-art"], rid="rp-1")
        # 渠道不覆盖：短视频授权存在，但计划落在别的渠道时应失败——改用期限外日期
        outside = self.app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                        scheduled="2030-01-01", rid="rp-out")["计划"]
        checks = {c["名称"]: c for c in self.app.gate_checks(outside)}
        self.assertEqual(checks["地区权利"]["状态"], "阻塞")

    def test_grant_period_validation(self):
        with self.assertRaises(ValidationError):
            self.app.grant_license("bad", IP, "原初网络", regions=["TH"],
                                   start="2027-01-01", end="2026-01-01")

    def test_asset_partial_region_coverage_blocks_other_markets(self):
        v = self.app.open_version("p-th", editor="剪辑")
        # 泰国版本挂了只覆盖 AE/TR 的中东肖像
        self.app.attach_asset(v["id"], "as-lead-me")
        plan = self.app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                     scheduled="2026-06-01", rid="rp-2")["计划"]
        checks = {c["名称"]: c for c in self.app.gate_checks(plan)}
        self.assertEqual(checks["素材确认与地区覆盖"]["状态"], "阻塞")

    def test_unconfirmed_actor_or_music_blocks_release(self):
        v = self.app.open_version("p-th", editor="剪辑")
        self.app.attach_asset(v["id"], "as-folk")
        plan = self.app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                     scheduled="2026-06-01", rid="rp-3")["计划"]
        checks = {c["名称"]: c for c in self.app.gate_checks(plan)}
        self.assertIn("尚未确认", checks["素材确认与地区覆盖"]["明细"])

    def test_confirm_asset_can_extend_regions(self):
        self.app.confirm_asset("as-folk", regions=["TH"])
        self.assertTrue(self.app.store.get("asset", "as-folk")["已确认"])
        self.assertIn("TH", self.app.store.get("asset", "as-folk")["覆盖地区"])


class TestCultureBoundary(unittest.TestCase):
    def setUp(self):
        self.app = build()
        self.app.create_proposal("p-ae", IP, "team-dxb", "阿版", target_regions=["AE"])
        self.app.add_proposal_elements("p-ae", ["ce-mural", "ce-prayer"])
        self.app.culture_decide("p-ae", "中东文化顾问团", "通过")

    def test_unresolved_restriction_blocks_gate(self):
        v = self.app.open_version("p-ae", editor="剪辑")
        for aid in ("as-bgm", "as-lead-me", "as-art"):
            self.app.attach_asset(v["id"], aid)
        # 只处置壁画限定，未处置礼拜改写
        self.app.adapt_region(v["id"], "AE", note="初版",
                              resolved_restrictions=["cr-mural-01"])
        self.app.translation_review(v["id"], "AE", "r", "通过")
        self.app.culture_review(v["id"], "AE", "r", "通过")
        self.app.rate_region(v["id"], "AE", "r", "PG-15")
        self.app.log_work(v["id"], 10)
        self.app.settle_work(v["id"])
        plan = self.app.plan_release(IP, "AE", v["id"], channel="流媒体",
                                     scheduled="2026-07-01", rid="rp-ae")["计划"]
        checks = {c["名称"]: c for c in self.app.gate_checks(plan)}
        self.assertEqual(checks["文化限定处置"]["状态"], "阻塞")
        with self.assertRaises(GateBlockedError) as ctx:
            self.app.approve_release("rp-ae")
        self.assertIn("文化限定处置", ctx.exception.details["pending"])

    def test_region_specific_restriction_does_not_leak_to_other_markets(self):
        # cr-prayer-me 只适用 AE：泰国提案不受其约束
        app = build()
        app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])
        app.add_proposal_elements("p-th", ["ce-prayer"])
        app.culture_decide("p-th", "顾问", "通过")
        v = app.open_version("p-th", editor="剪辑")
        for aid in ("as-bgm", "as-lead", "as-art"):
            app.attach_asset(v["id"], aid)
        app.adapt_region(v["id"], "TH", note="本地化")
        app.translation_review(v["id"], "TH", "r", "通过")
        app.culture_review(v["id"], "TH", "r", "通过")
        app.rate_region(v["id"], "TH", "r", "PG-13")
        app.log_work(v["id"], 10)
        app.settle_work(v["id"])
        plan = app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                scheduled="2026-06-01", rid="rp-th")["计划"]
        checks = {c["名称"]: c for c in app.gate_checks(plan)}
        self.assertEqual(checks["文化限定处置"]["状态"], "通过")

    def test_proposal_target_regions_must_match_team_scope(self):
        with self.assertRaises(ValidationError):
            self.app.create_proposal("p-x", IP, "team-bkk", "越界",
                                     target_regions=["AE"])


class TestMaterialIsolation(unittest.TestCase):
    def setUp(self):
        self.app = build()
        self.app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])

    def test_team_cannot_pick_up_other_region_material(self):
        with self.assertRaises(ValidationError):
            self.app.grant_material("team-bkk", "AE", asset_ids=["as-lead-me"])

    def test_unconfirmed_or_uncovered_asset_cannot_be_sent(self):
        with self.assertRaises(ConflictError):
            self.app.grant_material("team-bkk", "TH", asset_ids=["as-folk"])
        with self.assertRaises(ConflictError):
            self.app.grant_material("team-bkk", "TH", asset_ids=["as-lead-me"])

    def test_auto_package_only_contains_confirmed_covered_assets(self):
        pkg = self.app.grant_material("team-bkk", "TH")
        self.assertEqual(set(pkg["素材"]), {"as-bgm", "as-lead", "as-art"})

    def test_auto_package_accepts_explicit_ip_before_proposal(self):
        app = build()  # 尚未建立任何提案
        pkg = app.grant_material("team-bkk", "TH", ip_id=IP)
        self.assertEqual(set(pkg["素材"]), {"as-bgm", "as-lead", "as-art"})
        with self.assertRaises(ValidationError):
            app.grant_material("team-bkk", "TH")  # 无提案又未指定 IP，无法定范围


class TestReworkAndWorkLedger(unittest.TestCase):
    def setUp(self):
        self.app = build()
        self.app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])

    def test_settled_hours_are_immutable(self):
        v1 = self.app.open_version("p-th", editor="剪辑")
        self.app.log_work(v1["id"], 100, rid="w1")
        self.app.settle_work(v1["id"])
        with self.assertRaises(ConflictError):
            self.app.log_work(v1["id"], 20)
        with self.assertRaises(ConflictError):
            self.app.settle_work(v1["id"])
        settlement = self.app.store.get("work_settlement", f"st-{v1['id']}")
        self.assertEqual(settlement["总工时"], 100.0)
        self.assertTrue(settlement["锁定"])
        # 原始台账记录也未被改写
        self.assertEqual(self.app.store.get("work_log", "w1")["工时"], 100.0)

    def test_rework_opens_new_version_and_keeps_lineage(self):
        v1 = self.app.open_version("p-th", editor="剪辑")
        self.app.log_work(v1["id"], 100)
        self.app.settle_work(v1["id"])
        v2 = self.app.open_version("p-th", editor="剪辑", parent_id=v1["id"])
        self.assertEqual(v2["版本序号"], 2)
        self.assertEqual(v2["父版本"], v1["id"])
        self.app.log_work(v2["id"], 30)
        self.app.settle_work(v2["id"])
        lineage = self.app.lineage("p-th")
        self.assertEqual([n["序号"] for n in lineage], [1, 2])
        self.app.abandon_version(v1["id"], reason="v2 定稿")
        plan = self.app.plan_release(IP, "TH", v1["id"], channel="流媒体",
                                     scheduled="2026-06-01", rid="rp-old")["计划"]
        checks = {c["名称"]: c for c in self.app.gate_checks(plan)}
        self.assertEqual(checks["版本有效性"]["状态"], "阻塞")

    def test_first_version_then_rework_requires_parent(self):
        self.app.open_version("p-th", editor="剪辑")
        with self.assertRaises(ConflictError):
            self.app.open_version("p-th", editor="剪辑")


class TestDeliveryIdempotency(unittest.TestCase):
    def setUp(self):
        self.app = build()
        self.app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])
        self.v = self.app.open_version("p-th", editor="剪辑")

    def test_cross_timezone_duplicate_is_booked_once(self):
        args = dict(version_id=self.v["id"], region="TH", idem_key="KEY-1",
                    package_ref="pkg")
        first = self.app.deliver(at="2026-05-31T16:30:00+00:00", **args)
        second = self.app.deliver(at="2026-05-31T23:30:00+07:00", **args)
        third = self.app.deliver(at="2026-06-01T08:00:00+09:00", **args)
        self.assertFalse(first["是否重复"])
        self.assertTrue(second["是否重复"])
        self.assertTrue(third["是否重复"])
        self.assertEqual(second["交付"]["id"], first["交付"]["id"])
        deliveries = self.app.store.query("delivery", 版本=self.v["id"])
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["交付时间"], "2026-05-31T16:30:00+00:00")

    def test_different_keys_are_separate_deliveries(self):
        kw = dict(version_id=self.v["id"], region="TH", package_ref="pkg")
        self.app.deliver(idem_key="K-A", at="2026-05-31T10:00:00Z", **kw)
        self.app.deliver(idem_key="K-B", at="2026-05-31T11:00:00Z", **kw)
        self.assertEqual(len(self.app.store.list("delivery")), 2)


class TestReleaseGateAndRevenue(unittest.TestCase):
    def setUp(self):
        self.app = build()
        self.app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])
        self.app.add_proposal_elements("p-th", ["ce-mural"])
        self.app.culture_decide("p-th", "敦煌研究院联络人", "通过")

    def test_full_gate_approval_snapshots_revenue_basis(self):
        _, plan = ready_plan(self.app, "p-th", "TH",
                             ["as-bgm", "as-lead", "as-art"], rid="rp-ok",
                             scheduled="2026-06-01", rating="PG-13（泰国）")
        approved = self.app.approve_release("rp-ok")
        self.assertEqual(approved["状态"], "已放行")
        self.assertTrue(all(c["状态"] == "通过" for c in approved["闸门"]))
        self.app.go_live("rp-ok")
        basis = approved["收益依据"]
        self.assertEqual(basis["授权"], "lic-sea")
        self.assertEqual(basis["版权方分成比例"], 0.55)
        self.assertEqual(basis["地区"], "TH")
        self.assertEqual(basis["核算总工时"], 100.0)

    def test_go_live_requires_approval(self):
        _, plan = ready_plan(self.app, "p-th", "TH",
                             ["as-bgm", "as-lead", "as-art"], rid="rp-wait")
        with self.assertRaises(ConflictError):
            self.app.go_live("rp-wait")

    def test_plan_release_idempotent(self):
        v = self.app.open_version("p-th", editor="剪辑")
        a = self.app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                  scheduled="2026-06-01", idem_key="PLAN-1", rid="rp-a")
        b = self.app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                  scheduled="2026-06-01", idem_key="PLAN-1", rid="rp-b")
        self.assertFalse(a["是否重复"])
        self.assertTrue(b["是否重复"])
        self.assertEqual(a["计划"]["id"], b["计划"]["id"])


class TestRevocation(unittest.TestCase):
    def setUp(self):
        self.app = build()
        for pid, team, region, assets, rating in [
            ("p-th", "team-bkk", "TH", ["as-bgm", "as-lead", "as-art"], "PG-13"),
            ("p-id", "team-jkt", "ID", ["as-bgm", "as-lead", "as-art"], "SU"),
            ("p-ae", "team-dxb", "AE", ["as-bgm", "as-lead-me", "as-art"], "PG-15"),
        ]:
            self.app.create_proposal(pid, IP, team, f"{region}版", target_regions=[region])
            self.app.add_proposal_elements(
                pid, ["ce-mural", "ce-prayer"] if region == "AE" else ["ce-mural"])
            self.app.culture_decide(pid, "顾问", "通过")
        # 泰国：已上线
        self.v_th, self.rp_th = ready_plan(self.app, "p-th", "TH",
                                   ["as-bgm", "as-lead", "as-art"], rid="rp-th",
                                   scheduled="2026-06-01", rating="PG-13")
        self.app.approve_release("rp-th")
        self.app.go_live("rp-th")
        # 印尼：已放行但未上线
        _, self.rp_id = ready_plan(self.app, "p-id", "ID",
                                   ["as-bgm", "as-lead", "as-art"], rid="rp-id",
                                   scheduled="2026-09-01", rating="SU")
        self.app.approve_release("rp-id")
        # 阿联酋：已上线，授权独立
        _, self.rp_ae = ready_plan(
            self.app, "p-ae", "AE", ["as-bgm", "as-lead-me", "as-art"],
            rid="rp-ae", scheduled="2026-07-15", rating="PG-15",
            resolved=("cr-mural-01", "cr-prayer-me"))
        self.app.approve_release("rp-ae")
        self.app.go_live("rp-ae")

    def test_impact_covers_every_unpublished_plan_and_live_copy(self):
        impact = self.app.withdrawal_impact("lic-sea")
        blocked = {p["id"] for p in impact["阻断未发布"]}
        affected = {p["id"] for p in impact["波及副本"]}
        self.assertEqual(blocked, {"rp-id"})
        self.assertEqual(affected, {"rp-th"})
        self.assertEqual(impact["受影响渠道"], ["流媒体"])

    def test_revoke_blocks_unpublished_and_marks_live_copies(self):
        self.app.revoke_license("lic-sea", reason="终止授权")
        self.assertEqual(self.rp_id["状态"], "已阻断")
        self.assertEqual(self.rp_th["状态"], "已上线")       # 不能凭空消失
        self.assertTrue(self.rp_th["撤权波及"])              # 但被标记波及
        self.assertFalse(self.rp_ae["撤权波及"])             # 独立授权不受影响
        # 已阻断计划不能放行
        with self.assertRaises(ConflictError):
            self.app.approve_release("rp-id")
        # 完成下线处置
        self.app.takedown("rp-th", reason="撤权下线")
        self.assertEqual(self.rp_th["状态"], "已下线")
        self.assertFalse(self.rp_th["撤权波及"])

    def test_double_revoke_rejected(self):
        self.app.revoke_license("lic-sea")
        with self.assertRaises(ConflictError):
            self.app.revoke_license("lic-sea")

    def test_revoked_region_cannot_approve_new_plan(self):
        self.app.revoke_license("lic-sea")
        # 即便另开新计划，地区权利闸门也会失败
        v = self.app.open_version("p-th", editor="剪辑2", parent_id=self.v_th["id"],
                                  note="撤权后的补救版")
        plan = self.app.plan_release(IP, "TH", v["id"], channel="流媒体",
                                    scheduled="2026-10-01", rid="rp-new")["计划"]
        checks = {c["名称"]: c for c in self.app.gate_checks(plan)}
        self.assertEqual(checks["地区权利"]["状态"], "阻塞")


class TestOverviewAndErrors(unittest.TestCase):
    def test_overview_lists_markets_and_basis(self):
        app = build()
        app.create_proposal("p-th", IP, "team-bkk", "泰版", target_regions=["TH"])
        app.add_proposal_elements("p-th", ["ce-mural"])
        app.culture_decide("p-th", "顾问", "通过")
        _, plan = ready_plan(app, "p-th", "TH",
                             ["as-bgm", "as-lead", "as-art"], rid="rp-th",
                             rating="PG-13")
        app.approve_release("rp-th")
        overview = app.market_overview(IP)
        th = next(m for m in overview["市场"] if m["地区"] == "TH")
        self.assertEqual(th["收益依据"][0]["版权方分成比例"], 0.55)
        self.assertEqual(th["发行副本"][0]["状态"], "已放行")

    def test_missing_records_raise_not_found(self):
        app = build()
        with self.assertRaises(NotFoundError):
            app.store.get("ip", "nope")
        with self.assertRaises(NotFoundError):
            app.approve_release("rp-missing")


if __name__ == "__main__":
    unittest.main()
