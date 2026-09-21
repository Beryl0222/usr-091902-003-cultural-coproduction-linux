# 跨文化内容共制

协调丝路题材游戏/短剧出海中的**内容权利、本地化文化边界、境外制作与分市场发行**，
把原始 IP、文化元素、改编提案、地区权利、译审意见与制片交付连成可追溯的版本关系。

## 解决的业务问题

- **版本关系**：原始 IP → 改编提案（文化决议）→ 成片版本（返工形成父子谱系）→ 分市场发行副本。
- **地区权利矩阵**：版权方授权按 `地区 × 期限 × 渠道` 生效；素材（演员、音乐、画面）逐项确认且只覆盖部分地区。
- **文化边界**：文化顾问可对敏感元素加限定（可限定适用地区）；本地化方案须逐条处置限定并通过文化复核。
- **素材发放隔离**：境外制片团队只能领取其负责地区、且权利已确认覆盖该地区的素材。
- **发行闸门**：放行前同时核验 8 项——版本有效性、地区权利、素材确认与地区覆盖、文化限定处置、文化复核、译审意见、当地分级、工时核算；任一不过即列出未决阻塞。
- **工时不可改写**：版本工时核算后锁定；返工必须开新版本，旧台账保持不变。
- **跨时区交付幂等**：同一交付幂等键在任一时区重提只入账一次，以首次 UTC 事件时间为准。
- **撤权处置**：授权撤回立即阻断所有未发布计划（待核验/已放行），已上线副本标记"撤权波及"并列出渠道，等待下线；撤权前可先做影响分析。
- **收益分配依据**：放行时固化快照（授权、版权方分成比例、成片版本、核算工时与台账）。
- **管理看板**：`GET /ips/{id}/overview` 查看各市场所用成片、未决阻塞、收益依据与撤权波及的每个副本。

## 目录

```
domain/
  records.py   领域记录结构（IP/素材/文化元素/授权/提案/版本/工时/交付/发行）
  store.py     内存仓库与事件日志
  app.py       全部业务规则（CoproductionApp）
  seed.py      种子加载
  errors.py    稳定错误码（400/404/409/422）
fixtures/
  first_title.json  首部作品《丝路·流沙记》的权利矩阵（4 团队 / 4 市场 / 3 授权）
service.py     HTTP 服务（健康检查 + JSON API，启动自动装入种子）
scenario.py    首部作品多地上线端到端走查（可执行）
test_domain.py 领域不变量测试（25 项）
test_api.py    HTTP 契约测试
```

## 使用

```bash
python3 service.py --check     # 基础配置与种子检查
python3 scenario.py            # 走完整业务故事，输出每步 JSON
python3 service.py --port 8000 # 启动 API（自带种子数据）
npm test                       # 34 项测试（契约 + 领域 + HTTP）
```

## API 摘要

| 动作 | 接口 |
|---|---|
| IP / 团队 / 素材 / 文化元素 / 限定 | `POST /ips` `/teams` `/assets` `/culture-elements` `/restrictions`；`POST /assets/{id}/confirm` |
| 授权矩阵 | `POST /licenses`；`POST /licenses/{id}/revoke`；`GET /licenses/{id}/impact` |
| 提案与文化决议 | `POST /proposals` `/proposals/{id}/elements` `/proposals/{id}/culture-decisions`；`GET /proposals/{id}/lineage` |
| 版本/返工 | `POST /versions`（`父版本` 非空即返工）、`/versions/{id}/abandon` |
| 挂素材与本地化 | `POST /versions/{id}/assets`、`/versions/{id}/regions/{region}/adaptation` |
| 三审 | `POST /versions/{id}/reviews/{translation|culture|rating}` |
| 工时 | `POST /versions/{id}/work-logs`、`/versions/{id}/settle`（核算后锁定） |
| 素材发放 | `POST /material-grants`（自动打包只含已确认且覆盖该地区的素材） |
| 交付（幂等） | `POST /deliveries`（`幂等键` 去重，重复提交返回 `是否重复: true`） |
| 发行 | `POST /releases`；`GET /releases/{id}/gate`；`POST /releases/{id}/{approve,go-live,cancel,takedown}` |
| 看板 | `GET /ips/{id}/overview`；事件流 `GET /events` |

## 首部作品走查故事（scenario.py）

1. 泰国首版误用未确认的民间乐曲采样 → 闸门拦截，放行返回 409 与未决阻塞；
2. 返工开 v2：v1 的 120 工时核算后锁定不变，v2 的 25 工时单独入账；
3. 同一交付在 UTC、曼谷、东京三个时区提交三次，只入账一条；
4. 分地区素材包互不串货，越区/未确认素材发放均被拒绝；
5. 泰国版八闸全过放行上线，收益依据（版权方 55% 分成、工时台账）固化；
6. 阿联酋版礼拜桥段限定未处置先被拦，改写并复核通过后上线（版权方 60% 分成）；
7. 版权方撤回东南亚授权：印尼待上线计划被精确阻断（仅剩"地区权利"一项阻塞），
   泰国已上线副本被标记撤权波及并执行下线，阿联酋独立授权不受影响；
8. 管理看板汇总每个市场的成片、阻塞、收益依据与波及副本。
