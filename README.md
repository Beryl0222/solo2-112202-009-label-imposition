# 共用包装版面中的型号声明校勘

业务资料使用虚构编号和合成叙述。文本保持来件拼写和措辞。各表是独立的来源记录。
TSV 文件采用 UTF-8，首行为列名。行首 id 是该表的稳定记录号，空格和标点属于原文，空单元格表示来件未填。
日期时间采用所在地本地时间。资料内注明为编号列表的字段用竖线分隔。

## 资料字段

- `materials/claims.tsv`。market 是销售市场，scope 是原声明所属产品范围，parent 是事先有出处的引用记录。
- `materials/print_surfaces.tsv`。layer 从底到顶，removable 表示消费者何时可能移除。covers 是被该层完整覆盖的区域 id。
- `materials/dispatch.tsv`。promised 是已对外承诺的时间，空值表示尚未承诺。assets 是实际装好的组合，空值表示待安排。
- `materials/stock.tsv`。qty 是实际尚可分配数量，region 是印厂登记适用渠道。
- `materials/sales_channels.tsv`。stage_visibility 同时记录顾客从查看、付款到开盒所见的包装窗口。

## 运行资料检查

使用 CPython 3.11.2 和标准库。资料检查仅读取输入。

```sh
python3 pack_check.py
python3 -m unittest -v
```

## 编校与排产共享结果

对新到的资料包，用 `--directory` 指向按同样 TSV 契约整理的目录；所有结论都会按该包的文案、层级、渠道和数量重新计算：

```sh
# 终端查看完整 Markdown 报告
python3 pack_check.py --directory materials audit --today 2026-11-24

# 给编校和排产共享的 report.md / report.json
python3 pack_check.py --directory materials report --out reports/latest --today 2026-11-24

# 排产查询某个出货批号；JSON 便于接入其他系统
python3 pack_check.py --directory materials batch D1 --today 2026-11-24
python3 pack_check.py --directory materials batch D1 --json --today 2026-11-24
```

报告中的位置形如 `claims.tsv:3:15` 或 `print_surfaces.tsv:2:32`，分别是 TSV 文件名、数据行号（含表头）和字符列；JSON 还提供字段内字符区间与原文 quote。

当前样例包的核对结论：

- `P1` 的 “Compatible con 24 V” 与 `P2` 的 “Solo serie A” 被断成两处；`P2` 可在购买时揭走，因此该限定只能作为印厂内部核对线索，不能让裸 `P1` 合规。
- C4 已撤回甲系列 24 V 主张。`P1` 必须被永久覆盖或返印。
- `P4` 永久覆盖 `P1`，且有 “Solo 12 V. Serie A, lote V8.”，可给南区、甲系列 V8 的 `D1` 贴补放行；`I3/P4 × 60` 被该单锁定。
- `P3` 永久覆盖 `P1` 并完整给出乙系列 12 V 范围；已发的 `D2` 手中文本以叠贴后可见的 `P3` 为准，业务员应联系南区收货方。
- `D3` 是北区乙系列单；`I2/P3` 只登记南区，不能挪给北区，需北区市场的永久贴纸或调拨。
- `D4` 是甲系列 V9；`P4` 只覆盖 V8，不能跨批号使用，需新的甲/V9（或不写死批号）永久补正贴。通用 `P1` 盒胚在合格覆盖层存在时仍可使用。

排产分配在一次核对内按“已承诺优先、承诺日更早优先”锁定库存，剩余数量写入报告；不会把同一库存数量重复承诺给两个批次。`report.json` 中的 `planning.reservations` 和 `planning.stock` 是分配台账。
