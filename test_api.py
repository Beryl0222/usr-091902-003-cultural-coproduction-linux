"""HTTP API 契约测试：种子数据随服务自动装入。"""

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from service import Handler


from service import Api, Handler, build_app


class ApiContractTest(unittest.TestCase):
    def setUp(self):
        # 每个用例一个全新的已装种子数据的服务实例，避免状态串扰
        fresh_handler = type("FreshHandler", (Handler,),
                             {"api": Api(build_app(seed=True))})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), fresh_handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
        req = Request(f"{self.base_url}{path}", data=data, method=method,
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, json.load(resp)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_health_keeps_stable_identity(self):
        status, payload = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "cultural-coproduction")

    def test_seed_license_is_loaded(self):
        status, payload = self.call("GET", "/ips/ip-silkroad/overview")
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["作品"]["名称"], "丝路·流沙记")

    def test_full_flow_over_http(self):
        # 提案 → 文化决议 → 版本 → 三审 → 工时 → 发行核验
        self.call("POST", "/proposals",
                  {"id": "http-p-th", "ip": "ip-silkroad", "团队": "team-bkk",
                   "改编概述": "HTTP 联调泰版", "目标地区": ["TH"]})
        self.call("POST", "/proposals/http-p-th/elements", {"元素": ["ce-mural"]})
        status, payload = self.call(
            "POST", "/proposals/http-p-th/culture-decisions",
            {"顾问": "敦煌研究院联络人", "结论": "通过"})
        self.assertEqual(status, 200)

        status, payload = self.call("POST", "/versions",
                                    {"id": "http-v1", "proposal": "http-p-th",
                                     "剪辑负责人": "剪辑-TH"})
        self.assertEqual(status, 200)
        for aid in ("as-bgm", "as-lead", "as-art"):
            self.call("POST", "/versions/http-v1/assets", {"素材": aid})
        self.call("POST", "/versions/http-v1/regions/TH/adaptation",
                  {"说明": "本地化", "已处置限定": ["cr-mural-01"]})
        self.call("POST", "/versions/http-v1/reviews/translation",
                  {"地区": "TH", "审校人": "r", "结论": "通过"})
        self.call("POST", "/versions/http-v1/reviews/culture",
                  {"地区": "TH", "审校人": "r", "结论": "通过"})
        self.call("POST", "/versions/http-v1/reviews/rating",
                  {"地区": "TH", "审校人": "r", "分级": "PG-13"})
        self.call("POST", "/versions/http-v1/work-logs", {"工时": 80})
        status, payload = self.call("POST", "/versions/http-v1/settle", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["总工时"], 80.0)

        self.call("POST", "/releases",
                  {"id": "http-rp-th", "ip": "ip-silkroad", "地区": "TH",
                   "版本": "http-v1", "渠道": "流媒体", "计划上线": "2026-06-01"})
        status, payload = self.call("POST", "/releases/http-rp-th/approve", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["状态"], "已放行")

    def test_gate_blocked_returns_409_with_checks(self):
        self.call("POST", "/proposals",
                  {"id": "http-p-bad", "ip": "ip-silkroad", "团队": "team-bkk",
                   "改编概述": "缺审校版", "目标地区": ["TH"]})
        self.call("POST", "/versions",
                  {"id": "http-v-bad", "proposal": "http-p-bad", "剪辑负责人": "x"})
        self.call("POST", "/versions/http-v-bad/assets", {"素材": "as-folk"})
        self.call("POST", "/releases",
                  {"id": "http-rp-bad", "ip": "ip-silkroad", "地区": "TH",
                   "版本": "http-v-bad", "渠道": "流媒体", "计划上线": "2026-06-01"})
        status, payload = self.call("POST", "/releases/http-rp-bad/approve", {})
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "release_gate_blocked")
        self.assertIn("素材确认与地区覆盖", payload["details"]["pending"])

    def _publish_th(self, rid, vid):
        self.call("POST", "/proposals",
                  {"id": f"p-{rid}", "ip": "ip-silkroad", "团队": "team-bkk",
                   "改编概述": "联调泰版", "目标地区": ["TH"]})
        self.call("POST", f"/proposals/p-{rid}/elements", {"元素": ["ce-mural"]})
        self.call("POST", f"/proposals/p-{rid}/culture-decisions",
                  {"顾问": "敦煌研究院联络人", "结论": "通过"})
        self.call("POST", "/versions",
                  {"id": vid, "proposal": f"p-{rid}", "剪辑负责人": "剪辑-TH"})
        for aid in ("as-bgm", "as-lead", "as-art"):
            self.call("POST", f"/versions/{vid}/assets", {"素材": aid})
        self.call("POST", f"/versions/{vid}/regions/TH/adaptation",
                  {"说明": "本地化", "已处置限定": ["cr-mural-01"]})
        for path, body in [
            ("reviews/translation", {"地区": "TH", "审校人": "r", "结论": "通过"}),
            ("reviews/culture", {"地区": "TH", "审校人": "r", "结论": "通过"}),
            ("reviews/rating", {"地区": "TH", "审校人": "r", "分级": "PG-13"}),
        ]:
            self.call("POST", f"/versions/{vid}/{path}", body)
        self.call("POST", f"/versions/{vid}/work-logs", {"工时": 80})
        self.call("POST", f"/versions/{vid}/settle", {})
        self.call("POST", "/releases",
                  {"id": rid, "ip": "ip-silkroad", "地区": "TH", "版本": vid,
                   "渠道": "流媒体", "计划上线": "2026-06-01"})
        self.call("POST", f"/releases/{rid}/approve", {})

    def test_revoke_blocks_and_overview_reflects_it(self):
        self._publish_th("rp-live", "v-live")
        status, _ = self.call("POST", "/releases/rp-live/go-live", {})
        self.assertEqual(status, 200)
        # 同时放一个待上线计划，撤权后应被阻断
        self._publish_th("rp-wait", "v-wait")
        status, payload = self.call("POST", "/licenses/lic-sea/revoke",
                                    {"原因": "HTTP 联调撤权"})
        self.assertEqual(status, 200)
        affected = payload["data"]["影响"]["波及副本"]
        blocked = [p["id"] for p in payload["data"]["影响"]["阻断未发布"]]
        self.assertTrue(any(p["id"] == "rp-live" for p in affected))
        self.assertIn("rp-wait", blocked)
        status, payload = self.call("GET", "/ips/ip-silkroad/overview")
        th = next(m for m in payload["data"]["市场"] if m["地区"] == "TH")
        self.assertTrue(any(c["计划"] == "rp-live" for c in th["撤权波及副本"]))

    def test_missing_field_is_400_and_unknown_route_is_404(self):
        status, payload = self.call("POST", "/teams", {"id": "t"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "missing_field")
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"{self.base_url}/unknown", timeout=2)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
