# hard_household_moveout_deposit_hm37 中文说明

这个 Markdown 是给人看的任务说明，agent 不会读取它。agent 只会收到 JSON task instruction，并通过 tool 读取 `source_manifest.json` 中列出的 source 文件。

## 任务要做什么

任务场景是日常生活中的合租退租结算。Alex、Bri、Chen 三个人从 4B 单元搬出，需要根据最终合租规则、房东最终押金账单、押金出资记录、搬入/搬出检查记录、最终水电网账单，以及一个 Excel 形式的室友 side-adjustment 工作簿，计算每个人最终应该拿到的金额。

这个 hard 任务的难点是：

- 信息分散在 txt、md、csv、pdf、xlsx、docx 多种 source 中。
- 有很多看起来合理但必须排除的噪音，例如初稿估价、撤回扣款、其他单元记录、voided 押金、搬出后水电费、个人订阅、未批准购买、Excel 旧草稿页和重复/个人 side expense。
- 输出不再使用自由标签，而是要求返回 source 里的精确 ID、布尔值和金额，便于 deterministic eval。
- 最终金额需要经过多步推理：押金比例、房东扣款分摊、跨截止日水电账单 prorate、水电网净调整、Excel side-adjustment 按不同 allocation_rule 分摊、最终 payout。

## Agent 需要输出的字段

- `landlord_deduction_total`：只统计最终有效的房东押金扣款总额。
- `refund_pool`：有效总押金减去房东最终扣款；这是室友间水电网和 side adjustment 之前的退款池。
- `alex_landlord_deduction_share` / `bri_landlord_deduction_share` / `chen_landlord_deduction_share`：三个人按合租规则应承担的房东扣款份额。
- `alex_utility_adjustment` / `bri_utility_adjustment` / `chen_utility_adjustment`：每个人“已支付的纳入结算水电网金额 - 自己应承担的纳入结算水电网金额”。正数表示这个人应多拿回，负数表示应少拿回。
- `alex_final_refund` / `bri_final_refund` / `chen_final_refund`：每个人的有效押金出资 - 房东扣款份额 + 水电网调整额，还没有加 Excel side adjustment。
- `side_adjustment_total`：Excel 中最终纳入室友 side-adjustment 结算的金额总和。
- `alex_side_adjustment` / `bri_side_adjustment` / `chen_side_adjustment`：每个人“已支付的纳入 side adjustment 金额 - 自己按每行 allocation_rule 应承担的 side adjustment 金额”。
- `alex_final_payout` / `bri_final_payout` / `chen_final_payout`：每个人的 `final_refund + side_adjustment`。
- `approved_deduction_ids`：最终纳入房东押金扣款的 `item_id`，来自 `final_property_statement_hm37.csv`。
- `excluded_property_statement_ids`：从房东账单中排除的 `item_id`，来自 `final_property_statement_hm37.csv`。
- `valid_deposit_people`：押金 ledger 中 Unit 4B 且 `status=valid_final` 的人名。
- `excluded_deposit_row_ids`：押金 ledger 中应排除的 `row_id`，来自 `deposit_contributions_hm37.csv`。
- `included_utility_bill_ids`：纳入室友水电网结算的 `bill_id`，来自 `final_utilities_hm37.csv`。
- `excluded_utility_bill_ids`：排除出室友水电网结算的 `bill_id`，来自 `final_utilities_hm37.csv`。
- `included_side_adjustment_ids`：纳入室友 side-adjustment 结算的 `adjustment_id`，来自 `side_adjustment_workbook_hm37.xlsx`；对于 `requires_thread_approval` 行，还要结合 `roommate_approval_thread_hm37.docx`。
- `excluded_side_adjustment_ids`：从 side-adjustment 结算中排除的 `adjustment_id`，来自 `side_adjustment_workbook_hm37.xlsx`；没有三人一致批准的 `requires_thread_approval` 行也要排除。
- `refund_check_to_lead_tenant`：如果房东退款支票只发给 lead tenant，则为 `true`。
- `preliminary_estimate_conflict`：如果初稿报价和最终账单存在冲突或替代关系，则为 `true`。
- `roommate_reimbursement_needed`：如果水电网或 side adjustment 由不同室友代付且需要室友间二次调整，则为 `true`。

## Source 文件说明

`lease_and_housemate_rules_hm37.md`

当前有效的合租结算规则。关键规则包括：最终房东扣款才有效；共同或责任未知扣款按原始押金比例分摊；能归责到某个室友的扣款由该室友单独承担；草稿、撤回、其他单元、搬入前已有问题、天气损坏等都要排除。水电网账单只结算到 2026-03-31。文档里还有过期的 2024 平均分摊规则作为噪音，不能使用。

`final_property_statement_hm37.csv`

房东最终押金账单和若干干扰项。真正有效扣款是 F1、F2、F3、F4；X1、X2、D1、N1 都要排除。

`deposit_contributions_hm37.csv`

押金出资记录。有效记录是 Alex 1200、Bri 1050、Chen 750，总押金 3000。`DEP_ALEX_VOIDED_TOPUP` 是 voided，`DEP_DANA_4C` 属于 4C 单元，都不计入。

`final_utilities_hm37.csv`

最终水电网账单。计入 U1、U2、U3，以及按 2026-03-31 截止日 prorate 的 U7；排除搬出后的 U4、个人订阅 U5、未获批准的 U6、搬出后 gas true-up U8、被最终电费替代的估算项 U9。

`moveout_inspection_notes_hm37.md`

搬出检查记录，用来确认责任归属。客厅墙面 desk-anchor gouges 属于 Chen 的桌面区域；Bedroom B 百叶窗属于 Bri 的房间；清洁和钥匙责任未知；地毯和阳台纱窗不应向租客扣款。

`movein_condition_checklist_hm37.csv`

搬入检查记录。地毯在搬入时已经有旧污渍，因此地毯更换要排除。Bedroom B 百叶窗搬入时完好，所以搬出损坏可以扣 Bri。客厅墙面搬入时完好，所以新 gouges 可以扣 Chen。

`lead_tenant_email_hm37.txt`

房东邮件确认最终押金 3000、最终房东扣款 880、退款支票 2120 发给 lead tenant Alex。邮件也说明初稿估价已失效、地毯和阳台纱窗已移除、4C 停车遥控器不属于本结算。

`preliminary_cleaning_quote_hm37.txt`

过期初稿报价，是噪音 source。里面的清洁 475、地毯 900、油漆 525 都不能直接用于最终结算。

`repair_receipt_packet_hm37.pdf`

PDF 形式的最终收据包，重复确认最终有效扣款和撤回项目。

`side_adjustment_workbook_hm37.xlsx`

Excel 形式的室友 side-adjustment 工作簿。有效 sheet 是 `final_side_adjustments`，旧草稿 sheet `old_draft_do_not_use` 要作为噪音排除。`include_in_settlement=yes` 的 final 行可直接纳入；`requires_thread_approval` 的行必须去 Word 审批记录里核对三人是否都批准。最终纳入结算的是 SA1、SA2、SA3、SA10、SA13；SA4-SA9、SA11、SA12、SA14、SA15 和 OLD1-OLD3 都要排除。

`roommate_approval_thread_hm37.docx`

Word 形式的室友审批记录。它只用于判断 Excel 中 `requires_thread_approval` 的 side adjustment 行。SA13 在 2026-04-06 前得到 Alex、Bri、Chen 三人明确批准，因此纳入。SA14 被 Chen 拒绝，SA15 没有三人一致批准，因此排除。

## 解答过程

### 1. 计算押金比例

有效押金：

- Alex = 1200.00
- Bri = 1050.00
- Chen = 750.00
- 总押金 = 3000.00

押金比例：

- Alex = 1200 / 3000 = 40%
- Bri = 1050 / 3000 = 35%
- Chen = 750 / 3000 = 25%

### 2. 计算房东最终扣款

有效房东扣款：

- F1 清洁返工 = 285.00
- F2 邮箱钥匙 = 45.00
- F3 客厅墙面 = 420.00
- F4 Bedroom B 百叶窗 = 130.00

```text
landlord_deduction_total = 285 + 45 + 420 + 130 = 880.00
refund_pool = 3000 - 880 = 2120.00
```

排除项：

- X1：地毯更换，搬入前已有问题
- X2：阳台纱窗，天气损坏
- D1：初稿油漆估价，已被最终账单替代
- N1：4C 单元停车遥控器，不属于 4B/HM-37

### 3. 分摊房东扣款

共同或责任未知扣款：

```text
F1 + F2 = 285 + 45 = 330.00
```

按押金比例分摊：

- Alex: 330 * 40% = 132.00
- Bri: 330 * 35% = 115.50
- Chen: 330 * 25% = 82.50

个人责任扣款：

- F3 客厅墙面 420.00，由 Chen 承担
- F4 Bedroom B 百叶窗 130.00，由 Bri 承担

所以房东扣款份额：

- Alex = 132.00
- Bri = 115.50 + 130.00 = 245.50
- Chen = 82.50 + 420.00 = 502.50

### 4. 计算水电网调整

U1 3 月电费 192.60 由 Alex 支付。其中 EV add-on 36.00 只算 Alex，剩余 156.60 三人平分：

- Alex 电费责任 = 36.00 + 156.60 / 3 = 88.20
- Bri 电费责任 = 156.60 / 3 = 52.20
- Chen 电费责任 = 156.60 / 3 = 52.20

U2 3 月水费/垃圾费 96.00 由 Chen 支付，三人平分，每人 32.00。U3 3 月网络费 75.00 由 Bri 支付，三人平分，每人 25.00。

U7 gas heat 账单 144.00 由 Chen 支付，服务期是 2026-03-20 到 2026-04-04，共 16 个 inclusive service days。只纳入截至 2026-03-31 的 12 天：

```text
U7 included amount = 144.00 * 12 / 16 = 108.00
每人责任 = 108.00 / 3 = 36.00
```

每个人总应承担的水电网责任：

- Alex = 88.20 + 32.00 + 25.00 + 36.00 = 181.20
- Bri = 52.20 + 32.00 + 25.00 + 36.00 = 145.20
- Chen = 52.20 + 32.00 + 25.00 + 36.00 = 145.20

每个人实际已支付：

- Alex = 192.60
- Bri = 75.00
- Chen = 96.00 + U7 prorated 108.00 = 204.00

水电网调整额 = 已支付 - 应承担：

- Alex = 192.60 - 181.20 = 11.40
- Bri = 75.00 - 145.20 = -70.20
- Chen = 204.00 - 145.20 = 58.80

### 5. 计算 side adjustment

Excel 中纳入结算的 final approved side-adjustment：

- SA1 = 18.00，由 Alex 支付
- SA2 = 90.00，由 Bri 支付
- SA3 = 6.00，由 Alex 支付
- SA10 = 75.00，由 Chen 支付，按押金比例分摊
- SA13 = 84.00，由 Alex 支付，按押金比例分摊；Word 审批记录显示三人均批准

```text
side_adjustment_total = 18 + 90 + 6 + 75 + 84 = 273.00
SA1-SA3 equal_split 总额 = 114.00，每人责任 = 38.00
SA10+SA13 deposit_share 总额 = 159.00
Alex 159*40%=63.60, Bri 159*35%=55.65, Chen 159*25%=39.75
```

每个人实际支付的 side adjustment：

- Alex = 18 + 6 + 84 = 108.00
- Bri = 90.00
- Chen = 75.00

每个人总 side responsibility：

- Alex = 38.00 + 63.60 = 101.60
- Bri = 38.00 + 55.65 = 93.65
- Chen = 38.00 + 39.75 = 77.75

side adjustment = 已支付 - 应承担：

- Alex = 108.00 - 101.60 = 6.40
- Bri = 90.00 - 93.65 = -3.65
- Chen = 75.00 - 77.75 = -2.75

排除的 Excel 项：

- SA4：draft row，不是 final
- SA5：personal_subset moving truck，不是三人共同结算
- SA6：personal donation pickup，不是三人共同结算
- SA7：duplicate landlord wall repair，和房东 F3 重复
- SA8：voided old Venmo request
- SA9：other_unit 4C
- SA11：Alex 个人 packing tape
- SA12：SA2 的 draft duplicate
- SA14：requires_thread_approval，但 Chen 未批准
- SA15：requires_thread_approval，但没有三人一致批准
- OLD1、OLD2、OLD3：位于 old draft sheet，要排除

### 6. 计算最终 payout

先计算 side adjustment 前的退款：

- Alex = 1200 - 132.00 + 11.40 = 1079.40
- Bri = 1050 - 245.50 - 70.20 = 734.30
- Chen = 750 - 502.50 + 58.80 = 306.30

再加 side adjustment：

- Alex = 1079.40 + 6.40 = 1085.80
- Bri = 734.30 - 3.65 = 730.65
- Chen = 306.30 - 2.75 = 303.55

校验：

```text
1085.80 + 730.65 + 303.55 = 2120.00
```

## Gold output

```json
{
  "landlord_deduction_total": 880.0,
  "refund_pool": 2120.0,
  "alex_landlord_deduction_share": 132.0,
  "bri_landlord_deduction_share": 245.5,
  "chen_landlord_deduction_share": 502.5,
  "alex_utility_adjustment": 11.4,
  "bri_utility_adjustment": -70.2,
  "chen_utility_adjustment": 58.8,
  "alex_final_refund": 1079.4,
  "bri_final_refund": 734.3,
  "chen_final_refund": 306.3,
  "side_adjustment_total": 273.0,
  "alex_side_adjustment": 6.4,
  "bri_side_adjustment": -3.65,
  "chen_side_adjustment": -2.75,
  "alex_final_payout": 1085.8,
  "bri_final_payout": 730.65,
  "chen_final_payout": 303.55,
  "approved_deduction_ids": ["F1", "F2", "F3", "F4"],
  "excluded_property_statement_ids": ["X1", "X2", "D1", "N1"],
  "valid_deposit_people": ["Alex", "Bri", "Chen"],
  "excluded_deposit_row_ids": ["DEP_ALEX_VOIDED_TOPUP", "DEP_DANA_4C"],
  "included_utility_bill_ids": ["U1", "U2", "U3", "U7"],
  "excluded_utility_bill_ids": ["U4", "U5", "U6", "U8", "U9"],
  "included_side_adjustment_ids": ["SA1", "SA2", "SA3", "SA10", "SA13"],
  "excluded_side_adjustment_ids": ["SA4", "SA5", "SA6", "SA7", "SA8", "SA9", "SA11", "SA12", "SA14", "SA15", "OLD1", "OLD2", "OLD3"],
  "refund_check_to_lead_tenant": true,
  "preliminary_estimate_conflict": true,
  "roommate_reimbursement_needed": true
}
```

## Gold output 的依据

- `landlord_deduction_total = 880.0` 来自最终房东账单 F1-F4；草稿、撤回、其他单元都排除。
- `refund_pool = 2120.0` 来自总押金 3000.0 减去最终房东扣款 880.0。
- 三个人房东扣款份额来自合租规则：共同/未知责任按押金比例，个人责任按检查记录归责。
- 三个人水电网调整来自 U1、U2、U3，以及按 12/16 天 prorate 的 U7；U4、U5、U6、U8、U9 都排除。
- 三个人 side adjustment 来自 Excel 和 Word 审批记录：SA1、SA2、SA3、SA10、SA13 纳入；SA1-SA3 equal split，SA10 和 SA13 按押金比例；其他 sheet、draft、voided、personal、duplicate、other unit、无三人一致批准项都排除。
- `refund_check_to_lead_tenant=true` 来自 lead tenant 邮件。
- `preliminary_estimate_conflict=true` 来自初稿报价和最终邮件说明。
- `roommate_reimbursement_needed=true` 来自 utility 和 side adjustment 的代付人与责任人不完全一致。
