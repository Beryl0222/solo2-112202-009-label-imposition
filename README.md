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
