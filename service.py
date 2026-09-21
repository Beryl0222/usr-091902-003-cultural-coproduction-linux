"""跨文化内容共制运行入口：健康检查 + 领域 JSON API。"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from domain import CoproductionApp, DomainError, Store
from domain.seed import load_first_title

SERVICE_ID = "cultural-coproduction"
SERVICE_NAME = "跨文化内容共制"


def build_app(seed=True):
    store = Store()
    if seed:
        load_first_title(store)
    return CoproductionApp(store)


def health_payload():
    """返回稳定的服务身份信息。"""
    return {"status": "ok", "service": SERVICE_ID, "name": SERVICE_NAME}


# ── API 路由表：方法 + 正则 → (处理函数名, 参数名) ─────────────────

ROUTES = []


def route(method, pattern):
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)

    def deco(func):
        ROUTES.append((method, re.compile(f"^{regex}$"), func))
        return func
    return deco


class Api:
    """无状态外观：把 HTTP 入参映射到 CoproductionApp。"""

    def __init__(self, app):
        self.app = app

    @route("POST", "/ips")
    def create_ip(self, body, _p):
        return self.app.register_ip(body["id"], body["名称"], kind=body["作品类别"],
                                    rights_holder=body["原始版权方"],
                                    summary=body.get("简介", ""))

    @route("POST", "/teams")
    def create_team(self, body, _p):
        return self.app.register_team(body["id"], body["名称"],
                                      regions=body["负责地区"], timezone=body["时区"])

    @route("POST", "/assets")
    def create_asset(self, body, _p):
        return self.app.register_asset(body["id"], body["ip"], body["名称"],
                                       kind=body["素材类别"], owner=body["权利方"],
                                       confirmed=body.get("已确认", False),
                                       regions=body.get("覆盖地区"))

    @route("POST", "/assets/{id}/confirm")
    def confirm_asset(self, body, p):
        return self.app.confirm_asset(p["id"], note=body.get("备注", ""),
                                      regions=body.get("覆盖地区"))

    @route("POST", "/culture-elements")
    def create_element(self, body, _p):
        return self.app.register_culture_element(body["id"], body["ip"], body["名称"],
                                                 sensitivity=body.get("敏感级别", "普通"))

    @route("POST", "/restrictions")
    def add_restriction(self, body, _p):
        return self.app.add_restriction(body["元素"], body["顾问"], body["限定要求"],
                                        regions=body.get("适用地区"), rid=body.get("id"))

    @route("POST", "/licenses")
    def grant_license(self, body, _p):
        return self.app.grant_license(body["id"], body["ip"], body["版权方"],
                                      regions=body["授权地区"], start=body["开始"],
                                      end=body["结束"], exclusive=body.get("独家", False),
                                      channels=body.get("渠道"),
                                      revenue_share=body.get("分成比例", 0.0))

    @route("POST", "/licenses/{id}/revoke")
    def revoke_license(self, body, p):
        return self.app.revoke_license(p["id"], reason=body.get("原因", ""))

    @route("GET", "/licenses/{id}/impact")
    def license_impact(self, _b, p):
        return self.app.withdrawal_impact(p["id"])

    @route("POST", "/proposals")
    def create_proposal(self, body, _p):
        return self.app.create_proposal(body["id"], body["ip"], body["团队"],
                                        body["改编概述"], target_regions=body["目标地区"])

    @route("POST", "/proposals/{id}/elements")
    def proposal_elements(self, body, p):
        return self.app.add_proposal_elements(p["id"], body["元素"])

    @route("POST", "/proposals/{id}/culture-decisions")
    def culture_decide(self, body, p):
        return self.app.culture_decide(p["id"], body["顾问"], body["结论"],
                                       note=body.get("意见", ""))

    @route("GET", "/proposals/{id}/lineage")
    def lineage(self, _b, p):
        return {"谱系": self.app.lineage(p["id"])}

    @route("POST", "/versions")
    def open_version(self, body, _p):
        return self.app.open_version(body["proposal"], editor=body["剪辑负责人"],
                                     note=body.get("说明", ""),
                                     parent_id=body.get("父版本"), rid=body.get("id"))

    @route("POST", "/versions/{id}/abandon")
    def abandon_version(self, body, p):
        return self.app.abandon_version(p["id"], reason=body.get("原因", ""))

    @route("POST", "/versions/{id}/assets")
    def attach_asset(self, body, p):
        return self.app.attach_asset(p["id"], body["素材"], purpose=body.get("用途", ""))

    @route("POST", "/versions/{id}/regions/{region}/adaptation")
    def adapt_region(self, body, p):
        return self.app.adapt_region(p["id"], p["region"], note=body["说明"],
                                     resolved_restrictions=body.get("已处置限定"))

    @route("POST", "/versions/{id}/reviews/translation")
    def translation_review(self, body, p):
        return self.app.translation_review(p["id"], body["地区"], body["审校人"],
                                           body["结论"], note=body.get("意见", ""))

    @route("POST", "/versions/{id}/reviews/culture")
    def culture_review(self, body, p):
        return self.app.culture_review(p["id"], body["地区"], body["审校人"],
                                       body["结论"], note=body.get("意见", ""))

    @route("POST", "/versions/{id}/reviews/rating")
    def rate_region(self, body, p):
        return self.app.rate_region(p["id"], body["地区"], body["审校人"],
                                    body["分级"], note=body.get("意见", ""))

    @route("POST", "/versions/{id}/work-logs")
    def log_work(self, body, p):
        return self.app.log_work(p["id"], body["工时"], note=body.get("说明", ""),
                                 at=body.get("提交时间"), rid=body.get("id"))

    @route("POST", "/versions/{id}/settle")
    def settle_work(self, _b, p):
        return self.app.settle_work(p["id"])

    @route("POST", "/material-grants")
    def grant_material(self, body, _p):
        return self.app.grant_material(body["团队"], body["地区"],
                                       asset_ids=body.get("素材"),
                                       package_ref=body.get("包引用"),
                                       ip_id=body.get("ip"), rid=body.get("id"))

    @route("POST", "/deliveries")
    def deliver(self, body, _p):
        return self.app.deliver(body["版本"], body["地区"], idem_key=body["幂等键"],
                                package_ref=body["包引用"], at=body["交付时间"])

    @route("POST", "/releases")
    def plan_release(self, body, _p):
        return self.app.plan_release(body["ip"], body["地区"], body["版本"],
                                     channel=body["渠道"], scheduled=body["计划上线"],
                                     idem_key=body.get("幂等键"), rid=body.get("id"))

    @route("GET", "/releases/{id}/gate")
    def release_gate(self, _b, p):
        plan = self.app.store.get("release_plan", p["id"])
        return {"计划": p["id"], "状态": plan["状态"], "检查": self.app.gate_checks(plan)}

    @route("POST", "/releases/{id}/cancel")
    def cancel_release(self, body, p):
        return self.app.cancel_release(p["id"], reason=body.get("原因", ""))

    @route("POST", "/releases/{id}/approve")
    def approve_release(self, _b, p):
        return self.app.approve_release(p["id"])

    @route("POST", "/releases/{id}/go-live")
    def go_live(self, body, p):
        return self.app.go_live(p["id"], at=body.get("上线时间"))

    @route("POST", "/releases/{id}/takedown")
    def takedown(self, body, p):
        return self.app.takedown(p["id"], reason=body.get("原因", ""))

    @route("GET", "/ips/{id}/overview")
    def market_overview(self, _b, p):
        return self.app.market_overview(p["id"])

    @route("GET", "/events")
    def events(self, _b, _p):
        return {"事件": self.app.store.events}


class Handler(BaseHTTPRequestHandler):
    """提供健康检查与领域 JSON API，供本地联调和运维巡检使用。"""

    api = Api(build_app(seed=True))

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        if self.path == "/health":
            self._write_json(200, health_payload())
            return
        path = self.path.split("?", 1)[0]
        for verb, regex, func in ROUTES:
            if verb != method:
                continue
            match = regex.match(path)
            if not match:
                continue
            body = {}
            if method == "POST":
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError as exc:
                        self._write_json(400, {"code": "bad_json", "message": str(exc)})
                        return
            try:
                result = func(self.api, body, match.groupdict())
            except DomainError as exc:
                self._write_json(exc.status, exc.to_dict())
                return
            except KeyError as exc:
                self._write_json(400, {"code": "missing_field",
                                       "message": f"缺少字段：{exc.args[0]}"})
                return
            self._write_json(200, {"data": result})
            return
        self.send_error(404)

    def _write_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def main():
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-seed", action="store_true", help="启动时不装入种子数据")
    args = parser.parse_args()
    if args.check:
        assert health_payload()["service"] == SERVICE_ID
        app = build_app(seed=not args.no_seed)
        assert app.store.get("license_grant", "lic-sea")["状态"] == "生效"
        print("基础检查通过")
        return
    if args.no_seed:
        Handler.api = Api(CoproductionApp(Store()))
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
