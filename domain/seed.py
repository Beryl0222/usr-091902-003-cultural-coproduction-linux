"""种子数据加载：把 fixtures 中的主数据与权利矩阵装入仓库。"""

import json
import os

from . import records as R

_FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "fixtures")


def load_first_title(store):
    """装入首部作品《丝路·流沙记》的主数据与授权矩阵。"""
    path = os.path.join(_FIXTURE_DIR, "first_title.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    for row in data["ips"]:
        store.add(R.ip_work(row["id"], row["名称"], kind=row["作品类别"],
                            rights_holder=row["原始版权方"], summary=row.get("简介", "")))
    for row in data["teams"]:
        store.add(R.team(row["id"], row["名称"], regions=row["负责地区"],
                         timezone=row["时区"]))

    ip_id = data["ips"][0]["id"]
    for row in data["assets"]:
        store.add(R.asset(row["id"], ip_id, row["名称"], kind=row["素材类别"],
                          owner=row["权利方"], confirmed=row["已确认"],
                          regions=row["覆盖地区"]))
    for row in data["culture_elements"]:
        store.add(R.culture_element(row["id"], ip_id, row["名称"],
                                    sensitivity=row["敏感级别"]))
    for row in data["restrictions"]:
        store.add(R.culture_restriction(
            row["id"], row["元素"], row["顾问"], row["限定要求"],
            regions=row["适用地区"]))
        store.get("culture_element", row["元素"])["限定"].append(row["id"])
    for row in data["licenses"]:
        store.add(R.license_grant(
            row["id"], row["所属IP"], row["版权方"], regions=row["授权地区"],
            start=row["开始"], end=row["结束"], exclusive=row["独家"],
            channels=row["渠道"], revenue_share=row["分成比例"]))
    return data
