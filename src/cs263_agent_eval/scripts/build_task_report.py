"""Run one benchmark task and render a static HTML diagnostic report."""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from cs263_agent_eval.agents.runner import run_agentic_workflow, run_single_agent
from cs263_agent_eval.benchmark.hard_tasks import list_hard_task_ids, load_hard_task
from cs263_agent_eval.eval.scoring import score_prediction
from cs263_agent_eval.model_factory import get_small_ollama_llm, get_vertex_llm
from cs263_agent_eval.tools.local_tools import _read_any_file


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_ROOT = PROJECT_ROOT / "reports"
RUN_ROOT = REPORT_ROOT / "task_runs"
HTML_PATH = REPORT_ROOT / "task_diagnostics.html"

TASK_INSTRUCTION_TRANSLATIONS_ZH = {
    "hard_access_review_ar29": (
        "审查员工 E-443 的 IT 访问申请批次 AR-29。需要根据可用资料判断：哪些权限应该批准，"
        "哪些权限应该拒绝以及拒绝原因，请求整体风险等级是多少，在任何已批准权限正式开通前还需要哪些额外审批，"
        "如果要批准当前被拒绝的项目需要哪些策略例外，批次里哪些申请不属于本次 AR-29/E-443 审查而应排除，"
        "以及应标记哪些安全风险。评估时必须综合使用角色权限矩阵、数据访问策略和访问历史。"
        "最终只能返回 JSON 对象，字段包括：approved_permissions、denied_permissions、risk_level、"
        "required_approvals、policy_exceptions_needed、excluded_requests、risk_flags。"
        "approved_permissions 和 denied_permissions 都应使用简短 snake_case 标签表示资源和权限级别；"
        "risk_level 只能是 low、medium 或 high；required_approvals 表示开通已批准权限前还需要的审批角色；"
        "policy_exceptions_needed 表示若要批准当前被拒绝项所需的例外，若没有可覆盖的例外则为空；"
        "excluded_requests 表示属于其他批次或其他员工、因此不属于本次审查的申请；risk_flags 表示识别出的安全风险。"
        "risk_flags 需要列出资料直接支持的每一个独立安全风险原因，而不是只列最高层级风险。"
        "JSON 外不要输出解释。"
    ),
    "hard_household_moveout_deposit_hm37": (
        "审查 HM-37 合租退租结算，根据可用资料计算 4B 单元 Alex、Bri、Chen 的最终押金和水电网结算。"
        "还需要读取 Excel side-adjustment 工作簿，计算三人最终 payout。"
        "只能使用最终合租规则、最终房东账单、有效押金 ledger、检查证据、2026-03-31 及以前的水电网账单，以及 final approved 的 side-adjustment 行；跨 3/31 的账单如果 source 要求 prorate，需要只纳入截止日前的金额；side 行如果标成 requires_thread_approval，必须再读 roommate approval thread 判断三人是否都批准。"
        "需要排除初稿估价、撤回扣款、其他单元记录、voided 押金、搬入前已有损坏、天气损坏、个人订阅、未批准购买、搬出后费用、draft workbook 行、旧草稿 sheet、个人 side expense、重复 side expense 和未获三人批准的 side expense。"
        "输出字段包括房东最终扣款总额、退款池、三个人的房东扣款份额、水电网净调整、side-adjustment 净调整、side adjustment 后的最终 payout、各类纳入/排除 ID 以及三个结算流程风险 boolean。"
        "utility_adjustment 表示该室友已支付的纳入结算水电网金额减去其应承担金额；正数表示应多拿回，负数表示应少拿回。"
        "side_adjustment 表示该室友已支付的纳入 side adjustment 金额减去其按 allocation_rule 应承担金额；最终 payout 等于 final_refund 加 side_adjustment。"
        "refund_pool 是有效总押金减房东最终扣款，发生在室友间水电网和 side adjustment 调整之前。"
        "扣款、押金、账单和 Excel side-adjustment 选择必须输出 source 中的 item_id、row_id、bill_id 或 adjustment_id，不要自造描述性标签。"
        "三个风险字段输出 boolean。"
    )
}


def _json_block(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _text(value: Any) -> str:
    return html.escape(str(value))


def _task_instruction_zh(run: dict[str, Any]) -> str:
    return run.get("task_instruction_zh") or TASK_INSTRUCTION_TRANSLATIONS_ZH.get(
        run.get("task_id", ""),
        "暂无中文翻译。",
    )


def _source_payload(task) -> list[dict[str, str]]:
    payload = []
    for source_id, source_path in sorted(task.sources.items()):
        path = Path(str(source_path))
        try:
            content = _read_any_file(path)
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            content = f"Could not read source: {exc}"
        payload.append(
            {
                "source_id": source_id,
                "path": str(path.relative_to(PROJECT_ROOT)),
                "content": content,
            }
        )
    return payload


def _find_langsmith_trace_url(task_id: str, system_name: str, started_at: datetime) -> str | None:
    load_dotenv()
    if not os.getenv("LANGSMITH_API_KEY"):
        return None

    try:
        from langsmith import Client

        client = Client()
        project_name = os.getenv("LANGSMITH_PROJECT", "cs263-nlp")
        runs = client.list_runs(
            project_name=project_name,
            start_time=started_at - timedelta(minutes=2),
            is_root=True,
            limit=10,
        )
        fallback_url = None
        for run in runs:
            if fallback_url is None:
                fallback_url = getattr(run, "url", None)

            extra = getattr(run, "extra", {}) or {}
            metadata = extra.get("metadata", {}) if isinstance(extra, dict) else {}
            run_name = getattr(run, "name", "")
            if metadata.get("task_id") == task_id and metadata.get("system_name") == system_name:
                return getattr(run, "url", None)
            if run_name == f"{system_name}:{task_id}":
                return getattr(run, "url", None)
        return fallback_url
    except Exception:
        return None


def _run_system(task, system_name: str):
    if system_name == "large_single":
        return run_single_agent(task, get_vertex_llm(), "large_single")
    if system_name == "small_single":
        return run_single_agent(task, get_small_ollama_llm(), "small_single")
    if system_name == "small_workflow":
        return run_agentic_workflow(task, get_small_ollama_llm(), "small_agentic_workflow")
    raise ValueError(f"Unknown system: {system_name}")


def _failure_summary(scores) -> list[dict[str, Any]]:
    return [check for check in scores.details.get("checks", []) if not check.get("correct")]


HM37_EXACT_BASIS_ZH = {
    "landlord_deduction_total": "final_property_statement_hm37.csv 中 F1-F4 为 final_deducted，金额 285+45+420+130=880；lead_tenant_email_hm37.txt 也确认最终扣款为 880。",
    "refund_pool": "deposit_contributions_hm37.csv 的 valid_final 押金总额为 3000；lead_tenant_email_hm37.txt 确认退款支票为 2120，即 3000-880。",
    "alex_landlord_deduction_share": "lease_and_housemate_rules_hm37.md 要求共同/未知责任按押金比例分摊；Alex 押金占比 1200/3000=40%，只承担 F1+F2 的 40%。",
    "bri_landlord_deduction_share": "Bri 押金占比 35%，承担 F1+F2 的 35%，另根据 moveout_inspection_notes_hm37.md 承担 Bedroom B blinds 的 130。",
    "chen_landlord_deduction_share": "Chen 押金占比 25%，承担 F1+F2 的 25%，另根据 moveout_inspection_notes_hm37.md 承担 living room wall repair 的 420。",
    "alex_utility_adjustment": "final_utilities_hm37.csv 和 lease rules：U1 电费扣除 Alex EV add-on 后平分，U2/U3 平分，U7 gas 按 12/16 天 prorate 后 108 平分；Alex 已支付 192.60，应承担 181.20，调整额为 11.40。",
    "bri_utility_adjustment": "final_utilities_hm37.csv：Bri 支付网络 75，应承担 U1/U2/U3/U7 合计 145.20，所以调整额为 75-145.20=-70.20。",
    "chen_utility_adjustment": "final_utilities_hm37.csv：Chen 支付水费/垃圾费 96，并对 U7 只计入 prorated 108，纳入支付合计 204，应承担 145.20，所以调整额为 58.80。",
    "alex_final_refund": "Alex 押金基数为 1200-132=1068，再加 utility adjustment 11.40，最终 1079.40。",
    "bri_final_refund": "Bri 押金基数为 1050-245.50=804.50，再加 utility adjustment -70.20，最终 734.30。",
    "chen_final_refund": "Chen 押金基数为 750-502.50=247.50，再加 utility adjustment 58.80，最终 306.30。",
    "side_adjustment_total": "side_adjustment_workbook_hm37.xlsx 与 roommate_approval_thread_hm37.docx 共同确定 SA1、SA2、SA3、SA10、SA13 纳入结算，总额 18+90+6+75+84=273。",
    "alex_side_adjustment": "Alex 支付 SA1 18、SA3 6、SA13 84，共 108；SA1-SA3 equal split 责任 38，SA10+SA13 deposit_share 责任 63.60，总责任 101.60，所以 Alex 调整额为 6.40。",
    "bri_side_adjustment": "Bri 支付 SA2 90；SA1-SA3 equal split 责任 38，SA10+SA13 deposit_share 责任 55.65，总责任 93.65，所以 Bri 调整额为 -3.65。",
    "chen_side_adjustment": "Chen 支付 SA10 75；SA1-SA3 equal split 责任 38，SA10+SA13 deposit_share 责任 39.75，总责任 77.75，所以 Chen 调整额为 -2.75。",
    "alex_final_payout": "Alex final_refund 为 1079.40，再加 side_adjustment 6.40，最终 payout 为 1085.80。",
    "bri_final_payout": "Bri final_refund 为 734.30，再加 side_adjustment -3.65，最终 payout 为 730.65。",
    "chen_final_payout": "Chen final_refund 为 306.30，再加 side_adjustment -2.75，最终 payout 为 303.55。",
    "refund_check_to_lead_tenant": "lead_tenant_email_hm37.txt 说明 2120 退款支票只发给 lead tenant Alex。",
    "preliminary_estimate_conflict": "preliminary_cleaning_quote_hm37.txt 标注初稿报价；lead_tenant_email_hm37.txt 说明 April 2 preliminary estimate 不再有效。",
    "roommate_reimbursement_needed": "final_utilities_hm37.csv 和 side_adjustment_workbook_hm37.xlsx 显示代付人与责任人不完全一致，需要室友间二次调整。",
}

HM37_FIELD_REQUIREMENTS_ZH = {
    "landlord_deduction_total": "任务要求：只计算房东最终押金扣款总额，不包括水电网、初稿估价、撤回项或其他单元项目。",
    "refund_pool": "任务要求：有效总押金减去房东最终扣款；这是室友间水电网调整之前的押金退款池。",
    "alex_landlord_deduction_share": "任务要求：输出 Alex 按合租分摊规则应承担的房东扣款份额。",
    "bri_landlord_deduction_share": "任务要求：输出 Bri 按合租分摊规则应承担的房东扣款份额。",
    "chen_landlord_deduction_share": "任务要求：输出 Chen 按合租分摊规则应承担的房东扣款份额。",
    "alex_utility_adjustment": "任务要求：输出 Alex 的净水电网调整额，即已支付纳入结算的水电网金额减去自己应承担金额；正数表示多拿回。",
    "bri_utility_adjustment": "任务要求：输出 Bri 的净水电网调整额，即已支付纳入结算的水电网金额减去自己应承担金额；负数表示少拿回。",
    "chen_utility_adjustment": "任务要求：输出 Chen 的净水电网调整额，即已支付纳入结算的水电网金额减去自己应承担金额；负数表示少拿回。",
    "alex_final_refund": "任务要求：输出 Alex 的有效押金出资减去房东扣款份额，再加水电网调整额后的最终退款。",
    "bri_final_refund": "任务要求：输出 Bri 的有效押金出资减去房东扣款份额，再加水电网调整额后的最终退款。",
    "chen_final_refund": "任务要求：输出 Chen 的有效押金出资减去房东扣款份额，再加水电网调整额后的最终退款。",
    "side_adjustment_total": "任务要求：输出纳入结算的 final approved side-adjustment 行金额总和。",
    "alex_side_adjustment": "任务要求：输出 Alex 的 side-adjustment 净调整额，即已支付纳入 side adjustment 金额减去自己应承担金额。",
    "bri_side_adjustment": "任务要求：输出 Bri 的 side-adjustment 净调整额，即已支付纳入 side adjustment 金额减去自己应承担金额。",
    "chen_side_adjustment": "任务要求：输出 Chen 的 side-adjustment 净调整额，即已支付纳入 side adjustment 金额减去自己应承担金额。",
    "alex_final_payout": "任务要求：输出 Alex 的 final_refund 加 side_adjustment 后的最终 payout。",
    "bri_final_payout": "任务要求：输出 Bri 的 final_refund 加 side_adjustment 后的最终 payout。",
    "chen_final_payout": "任务要求：输出 Chen 的 final_refund 加 side_adjustment 后的最终 payout。",
    "approved_deductions": "任务要求：列出最终纳入结算的房东押金扣款项目；数组字段要包含全部且仅包含 source 直接支持的项目。",
    "excluded_items": "任务要求：列出所有 source 中明确应排除的项目，范围包括房东账单、押金 ledger、水电网账单和初稿报价；不能只输出类别级概括。",
    "utility_adjustments_applied": "任务要求：列出实际应用的水电网分摊规则；每个纳入结算的账单/分摊规则一个标签，3 月电费的平分和 Alex EV add-on 应合并成一个规则标签。",
    "risk_flags": "任务要求：列出 source 直接支持的结算流程风险，例如单人收款、初稿冲突、室友报销需求；不要输出泛化损坏风险。",
    "approved_deduction_ids": "任务要求：输出 final_property_statement_hm37.csv 中纳入结算的最终房东扣款 item_id。",
    "excluded_property_statement_ids": "任务要求：输出 final_property_statement_hm37.csv 中应排除的 item_id。",
    "valid_deposit_people": "任务要求：输出 deposit_contributions_hm37.csv 中 Unit 4B 且 status=valid_final 的 person。",
    "excluded_deposit_row_ids": "任务要求：输出 deposit_contributions_hm37.csv 中应排除的 row_id。",
    "included_utility_bill_ids": "任务要求：输出 final_utilities_hm37.csv 中纳入室友水电网结算的 bill_id，包括明确要求 prorate 的跨截止日账单。",
    "excluded_utility_bill_ids": "任务要求：输出 final_utilities_hm37.csv 中排除出室友水电网结算的 bill_id。",
    "included_side_adjustment_ids": "任务要求：输出 side_adjustment_workbook_hm37.xlsx 中纳入室友 side-adjustment 结算的 adjustment_id；requires_thread_approval 行必须由 roommate approval thread 确认三人批准。",
    "excluded_side_adjustment_ids": "任务要求：输出 side_adjustment_workbook_hm37.xlsx 中排除出室友 side-adjustment 结算的 adjustment_id；没有三人一致批准的 requires_thread_approval 行也要排除。",
    "refund_check_to_lead_tenant": "任务要求：如果房东退款支票只发给 lead tenant，则输出 true，否则 false。",
    "preliminary_estimate_conflict": "任务要求：如果初稿报价和最终账单存在冲突或替代关系，则输出 true，否则 false。",
    "roommate_reimbursement_needed": "任务要求：如果水电网或 side adjustment 由不同室友代付且需要室友间二次调整，则输出 true，否则 false。",
}

HM37_SET_ITEM_BASIS_ZH = {
    "cleaning_reclean": "final_property_statement_hm37.csv 的 F1 是 4B final_deducted cleaning re-clean；moveout_inspection_notes_hm37.md 说明清洁返工责任未知，应作为有效共同扣款。",
    "mailbox_key": "final_property_statement_hm37.csv 的 F2 是 4B final_deducted mailbox key replacement；moveout_inspection_notes_hm37.md 说明钥匙缺失且责任未知。",
    "living_room_wall_repair": "final_property_statement_hm37.csv 的 F3 是 final_deducted；moveout_inspection_notes_hm37.md 将客厅墙面 desk-anchor gouges 归责给 Chen。",
    "bedroom_b_blinds": "final_property_statement_hm37.csv 的 F4 是 final_deducted；moveout_inspection_notes_hm37.md 和 movein checklist 表明 Bedroom B blinds 搬入时完好、搬出损坏，归责 Bri。",
    "carpet_replacement_preexisting": "final_property_statement_hm37.csv 的 X1 是 withdrawn_preexisting；movein_condition_checklist_hm37.csv 说明 hall carpet 搬入时已有旧污渍。",
    "balcony_screen_weather_damage": "final_property_statement_hm37.csv 的 X2 是 withdrawn_weather_damage；moveout_inspection_notes_hm37.md 说明阳台纱窗为风暴天气损坏。",
    "unit_4c_parking_remote": "final_property_statement_hm37.csv 的 N1 unit=4C，lead_tenant_email_hm37.txt 明确 parking remote 属于 Unit 4C，不属于 HM-37。",
    "preliminary_paint_estimate": "final_property_statement_hm37.csv 的 D1 是 draft_superseded；preliminary_cleaning_quote_hm37.txt 标注 April 2 quote 已被最终账单替代。",
    "voided_alex_topup": "deposit_contributions_hm37.csv 中 Alex 100 top-up 状态为 voided_pending，不属于 valid_final 押金。",
    "unit_4c_deposit_row": "deposit_contributions_hm37.csv 中 Dana 的 500 属于 unit 4C，不属于 4B/HM-37。",
    "april_electric_after_moveout": "final_utilities_hm37.csv 的 U4 include_in_settlement=no，service period 是 2026-04-01 到 2026-04-15，已超过 2026-03-31 搬出结算截止。",
    "streaming_personal_subscription": "final_utilities_hm37.csv 的 U5 include_in_settlement=no，special_rule 是 personal_subscription。",
    "router_cable_unapproved": "final_utilities_hm37.csv 的 U6 include_in_settlement=no，special_rule 是 no_written_approval。",
    "electric_march_equal_split_with_ev_alex": "final_utilities_hm37.csv 的 U1 是 3 月电费，special_rule=ev_addon_36_to_alex；lease rules 要求 EV add-on 归 Alex，其余电费三人平分。",
    "water_trash_march_equal_split": "final_utilities_hm37.csv 的 U2 是 3 月 water_trash，include_in_settlement=yes，special_rule=equal_split。",
    "internet_march_equal_split": "final_utilities_hm37.csv 的 U3 是 3 月 internet，include_in_settlement=yes，special_rule=equal_split。",
    "refund_check_to_lead_tenant": "lead_tenant_email_hm37.txt 说明 2120 退款支票发给 lead tenant Alex，因此存在单人收款后的室友分配风险。",
    "preliminary_estimate_conflict": "preliminary_cleaning_quote_hm37.txt 和 lead_tenant_email_hm37.txt 都说明 April 2 初稿估价已失效，容易和最终账单冲突。",
    "roommate_reimbursement_needed": "final_utilities_hm37.csv 显示三个人分别代付不同账单，且 lease rules 要求室友间做 utility settlement，因此需要报销/调整。",
    "F1": "final_property_statement_hm37.csv 中 F1 为 Unit 4B 的 final_deducted 清洁返工扣款。",
    "F2": "final_property_statement_hm37.csv 中 F2 为 Unit 4B 的 final_deducted 邮箱钥匙替换扣款。",
    "F3": "final_property_statement_hm37.csv 中 F3 为 Unit 4B 的 final_deducted 客厅墙面修补扣款，inspection notes 归责 Chen。",
    "F4": "final_property_statement_hm37.csv 中 F4 为 Unit 4B 的 final_deducted Bedroom B 百叶窗扣款，inspection notes 归责 Bri。",
    "X1": "final_property_statement_hm37.csv 中 X1 为 withdrawn_preexisting，搬入检查记录显示地毯已有旧污渍。",
    "X2": "final_property_statement_hm37.csv 中 X2 为 withdrawn_weather_damage，搬出检查记录说明阳台纱窗为天气损坏。",
    "D1": "final_property_statement_hm37.csv 中 D1 为 draft_superseded，已被最终账单替代。",
    "N1": "final_property_statement_hm37.csv 中 N1 属于 Unit 4C，不属于 HM-37。",
    "Alex": "deposit_contributions_hm37.csv 中 Alex 的 DEP_ALEX_VALID 是 Unit 4B valid_final 押金记录。",
    "Bri": "deposit_contributions_hm37.csv 中 Bri 的 DEP_BRI_VALID 是 Unit 4B valid_final 押金记录。",
    "Chen": "deposit_contributions_hm37.csv 中 Chen 的 DEP_CHEN_VALID 是 Unit 4B valid_final 押金记录。",
    "DEP_ALEX_VOIDED_TOPUP": "deposit_contributions_hm37.csv 中 DEP_ALEX_VOIDED_TOPUP 状态为 voided_pending，应排除。",
    "DEP_DANA_4C": "deposit_contributions_hm37.csv 中 DEP_DANA_4C 属于 Unit 4C，应排除。",
    "U1": "final_utilities_hm37.csv 中 U1 是 2026-03-01 到 2026-03-31 的电费，include_in_settlement=yes。",
    "U2": "final_utilities_hm37.csv 中 U2 是 2026-03-01 到 2026-03-31 的 water_trash，include_in_settlement=yes。",
    "U3": "final_utilities_hm37.csv 中 U3 是 2026-03-01 到 2026-03-31 的 internet，include_in_settlement=yes。",
    "U4": "final_utilities_hm37.csv 中 U4 是 2026-04-01 到 2026-04-15 的搬出后电费，include_in_settlement=no。",
    "U5": "final_utilities_hm37.csv 中 U5 是 personal_subscription，include_in_settlement=no。",
    "U6": "final_utilities_hm37.csv 中 U6 是 no_written_approval 的 router cable，include_in_settlement=no。",
    "U7": "final_utilities_hm37.csv 中 U7 跨 2026-03-20 到 2026-04-04，include_in_settlement=partial，special_rule 要求只按 2026-03-31 前 12/16 天 prorate 纳入。",
    "U8": "final_utilities_hm37.csv 中 U8 是 2026-04-05 到 2026-04-19 的 post-move-out gas true-up，include_in_settlement=no。",
    "U9": "final_utilities_hm37.csv 中 U9 是 duplicate_estimate，已被 U1 final electric bill 替代，include_in_settlement=no。",
    "SA1": "side_adjustment_workbook_hm37.xlsx 的 final_side_adjustments sheet 中 SA1 为 final、include_in_settlement=yes、paid_by=Alex、amount=18，应纳入三人 equal split。",
    "SA2": "side_adjustment_workbook_hm37.xlsx 的 final_side_adjustments sheet 中 SA2 为 final、include_in_settlement=yes、paid_by=Bri、amount=90，应纳入三人 equal split。",
    "SA3": "side_adjustment_workbook_hm37.xlsx 的 final_side_adjustments sheet 中 SA3 为 final、include_in_settlement=yes、paid_by=Alex、amount=6，应纳入三人 equal split。",
    "SA10": "side_adjustment_workbook_hm37.xlsx 的 final_side_adjustments sheet 中 SA10 为 final、include_in_settlement=yes、paid_by=Chen、amount=75，allocation_rule=deposit_share。",
    "SA13": "side_adjustment_workbook_hm37.xlsx 中 SA13 为 requires_thread_approval；roommate_approval_thread_hm37.docx 显示 Alex、Bri、Chen 均在 2026-04-06 前批准，因此纳入。",
    "SA4": "side_adjustment_workbook_hm37.xlsx 中 SA4 是 draft full month April storage quote，include_in_settlement=no，应排除。",
    "SA5": "side_adjustment_workbook_hm37.xlsx 中 SA5 是 personal_subset moving truck rental，不是三人共同结算，include_in_settlement=no。",
    "SA6": "side_adjustment_workbook_hm37.xlsx 中 SA6 是 Chen 个人 donation pickup，不是三人共同结算，include_in_settlement=no。",
    "SA7": "side_adjustment_workbook_hm37.xlsx 中 SA7 是 duplicate landlord wall repair，与房东 F3 重复，include_in_settlement=no。",
    "SA8": "side_adjustment_workbook_hm37.xlsx 中 SA8 是 voided old Venmo request，include_in_settlement=no。",
    "SA9": "side_adjustment_workbook_hm37.xlsx 中 SA9 属于 Unit 4C，include_in_settlement=no。",
    "SA11": "side_adjustment_workbook_hm37.xlsx 中 SA11 是 Alex 个人 packing tape，include_in_settlement=no。",
    "SA12": "side_adjustment_workbook_hm37.xlsx 中 SA12 是 draft duplicate of SA2，include_in_settlement=no。",
    "SA14": "side_adjustment_workbook_hm37.xlsx 中 SA14 为 requires_thread_approval，但 roommate_approval_thread_hm37.docx 显示 Chen 未批准，因此排除。",
    "SA15": "side_adjustment_workbook_hm37.xlsx 中 SA15 为 requires_thread_approval，但 roommate_approval_thread_hm37.docx 显示没有三人一致批准，因此排除。",
    "OLD1": "side_adjustment_workbook_hm37.xlsx 的 old_draft_do_not_use sheet 是旧草稿，OLD1 不能纳入最终结算。",
    "OLD2": "side_adjustment_workbook_hm37.xlsx 的 old_draft_do_not_use sheet 是旧草稿，OLD2 不能纳入最终结算。",
    "OLD3": "side_adjustment_workbook_hm37.xlsx 的 old_draft_do_not_use sheet 是旧草稿，OLD3 不能纳入最终结算。",
}

AR29_EXACT_BASIS_ZH = {
    "risk_level": "access_history_ar29.txt 记录 E-443 有 PII 违规；access_requests_ar29.csv 同时请求 PII、audit logs、deployment write、PII delete；data_policy_ar29.md 对这些资源有严格限制，所以整体风险为 high。"
}

AR29_FIELD_REQUIREMENTS_ZH = {
    "approved_permissions": "任务要求：列出可以按当前 policy 授予的权限，使用简短 snake_case 标签。",
    "denied_permissions": "任务要求：列出不能按当前 policy 授予的权限，使用简短 snake_case 标签。",
    "risk_level": "任务要求：输出整体风险等级，只能是 low、medium 或 high。",
    "required_approvals": "任务要求：只列已批准权限在开通前还需要的审批；不要为已拒绝权限列审批。",
    "policy_exceptions_needed": "任务要求：只列能够使当前被拒项在所有 source 规则下变得可批准的例外；如果 denial 不可覆盖或 source 没说例外可覆盖所有 blocker，则留空。",
    "excluded_requests": "任务要求：列出不属于 AR-29/E-443 审查范围的其他批次或其他员工请求。",
    "risk_flags": "任务要求：列出 source 直接支持的每一个独立安全风险原因，不只列最高层级风险；历史违规、禁止权限、生产数据暴露、重复申请等应分别标记。",
}

AR29_SET_ITEM_BASIS_ZH = {
    "usage_reports_read": "role_permission_matrix_ar29.csv 明确 contractor 对 usage_reports 的 max_permission_level 是 read，且不需要额外审批。",
    "customer_pii_read": "access_requests_ar29.csv 的 R1 请求 customer_pii_database read；role_permission_matrix_ar29.csv 中 contractor 对 customer_pii_database 为 none，且 access_history_ar29.txt 有 prior PII violation。",
    "audit_logs_read": "access_requests_ar29.csv 的 R2 请求 internal_audit_logs read；data_policy_ar29.md 说明 contractor 不能直接读 audit logs，应走 supervised session。",
    "deployment_write": "access_requests_ar29.csv 的 R3 请求 deployment_pipeline write；data_policy_ar29.md 说明 deployment write 需要 engineer role 或以上。",
    "customer_pii_delete": "access_requests_ar29.csv 的 R4 请求 customer_pii_database delete；data_policy_ar29.md 明确 production database delete 权限永不授予 contractors。",
    "ar28_prior_batch": "access_requests_ar29.csv 的 N1 属于 AR-28/E-771，不是 AR-29/E-443；access_history_ar29.txt 也说明 AR-28 不属于本次审查。",
    "ar30_different_employee": "access_requests_ar29.csv 的 N2 属于 AR-30/E-551，不是 AR-29/E-443；access_history_ar29.txt 也说明 AR-30 来自不同员工。",
    "prior_pii_violation": "access_history_ar29.txt 记录 E-443 在 2026-02 有 PII/data handling warning，且仍在 lookback period。",
    "delete_access_contractor": "R4 请求 PII database delete；data_policy_ar29.md 的 Delete Permissions 明确 contractors 永不授予 production database delete。",
    "pii_production_access_requested": "R1 的 justification 是对 production data 做 QA tests；data_policy_ar29.md 要求 QA/testing 默认使用 anonymized/synthetic data。",
    "repeated_audit_log_denial": "access_history_ar29.txt 记录 E-443 在 2026-01 曾请求 internal_audit_logs read 并被拒；本次 R2 再次请求。",
}


def _task_item_basis_zh(task_id: str, expected: Any) -> str:
    expected_text = str(expected)
    if task_id == "hard_household_moveout_deposit_hm37":
        return (
            HM37_SET_ITEM_BASIS_ZH.get(expected_text)
            or HM37_SET_ITEM_BASIS_ZH.get(expected_text.upper())
            or HM37_SET_ITEM_BASIS_ZH.get(expected_text.title())
            or ""
        )
    if task_id == "hard_access_review_ar29":
        return AR29_SET_ITEM_BASIS_ZH.get(expected_text, "")
    return ""


def _field_basis_zh(task_id: str, field: str) -> str:
    if task_id == "hard_household_moveout_deposit_hm37":
        if field in HM37_EXACT_BASIS_ZH:
            return HM37_EXACT_BASIS_ZH[field]
        return {
            "approved_deductions": "final_property_statement_hm37.csv 只接受 status=final_deducted 且属于 Unit 4B 的扣款，并用 inspection notes 确认责任。",
            "excluded_items": "lease_and_housemate_rules_hm37.md 要求排除草稿、撤回、其他单元、voided、搬出后、个人订阅和未批准项目；各 source 对这些状态有明确标记。",
            "utility_adjustments_applied": "lease_and_housemate_rules_hm37.md 和 final_utilities_hm37.csv 只允许结算 2026-03-31 前的共同水电网，并应用 EV add-on 规则。",
            "risk_flags": "风险来自 lead tenant 单人收款、初稿报价和最终账单冲突、以及室友间水电网代付需要再分配。",
            "approved_deduction_ids": "final_property_statement_hm37.csv 中 status=final_deducted 且属于 Unit 4B 的 item_id 才纳入结算。",
            "excluded_property_statement_ids": "final_property_statement_hm37.csv 中 withdrawn、draft_superseded、other_unit 的 item_id 应排除。",
            "valid_deposit_people": "deposit_contributions_hm37.csv 中 Unit 4B 且 status=valid_final 的 person 是有效押金出资人。",
            "excluded_deposit_row_ids": "deposit_contributions_hm37.csv 中 voided_pending 或 other_unit 的 row_id 应排除。",
            "included_utility_bill_ids": "final_utilities_hm37.csv 中 include_in_settlement=yes 的账单，以及 include_in_settlement=partial 且规则要求 prorate through 2026-03-31 的账单应纳入。",
            "excluded_utility_bill_ids": "final_utilities_hm37.csv 中 after_moveout、personal_subscription、no_written_approval、duplicate_estimate 或未要求 prorate 的搬出后费用应排除。",
            "included_side_adjustment_ids": "side_adjustment_workbook_hm37.xlsx 中 final 且 include_in_settlement=yes 的行应纳入；requires_thread_approval 行只有在 roommate_approval_thread_hm37.docx 显示三人一致批准时纳入。",
            "excluded_side_adjustment_ids": "side_adjustment_workbook_hm37.xlsx 中 draft、old draft sheet、personal、personal_subset、duplicate、voided、other_unit、include_in_settlement=no，或 requires_thread_approval 但无三人一致批准的 adjustment_id 应排除。",
        }.get(field, "")
    if task_id == "hard_access_review_ar29":
        if field in AR29_EXACT_BASIS_ZH:
            return AR29_EXACT_BASIS_ZH[field]
        return {
            "approved_permissions": "role_permission_matrix_ar29.csv 决定 contractor 可以直接获得哪些权限。",
            "denied_permissions": "role_permission_matrix_ar29.csv、data_policy_ar29.md 和 access_history_ar29.txt 共同决定哪些请求必须拒绝。",
            "required_approvals": "只有已批准权限需要列开通前审批；AR-29 中唯一批准项 usage_reports_read 不需要额外审批。",
            "policy_exceptions_needed": "当前 gold 设计下，不列理论例外；被拒项由 role restriction、prior violation、supervised-session routing 或不可覆盖的 delete 禁令阻断。",
            "excluded_requests": "access_requests_ar29.csv 和 access_history_ar29.txt 明确 N1/N2 属于其他批次或其他员工。",
            "risk_flags": "安全风险来自 prior PII violation、production PII 请求、contractor delete 请求和重复 audit log 请求。",
        }.get(field, "")
    return ""


def _task_requirement_zh(task_id: str, field: str) -> str:
    if task_id == "hard_household_moveout_deposit_hm37":
        return HM37_FIELD_REQUIREMENTS_ZH.get(field, "")
    if task_id == "hard_access_review_ar29":
        return AR29_FIELD_REQUIREMENTS_ZH.get(field, "")
    return ""


def _check_basis_zh(task_id: str, check: dict[str, Any]) -> str:
    if check.get("type") == "set_contains":
        return _task_item_basis_zh(task_id, check.get("expected")) or _field_basis_zh(
            task_id, check.get("field", "")
        )
    return _field_basis_zh(task_id, check.get("field", ""))


def _check_explanation_zh(task_id: str, check: dict[str, Any], basis: str) -> str:
    expected = check.get("expected")
    actual = check.get("actual")
    unexpected = check.get("unexpected") or []

    if check.get("correct"):
        return "正确：模型输出与该检查项的 source 依据一致。"

    if check.get("type") == "exact":
        return f"错误：根据 source 应为 {expected}，但模型输出为 {actual}。{basis}"

    if check.get("type") == "set_contains":
        return f"错误：根据 source 该字段应包含 {expected}，但模型规范化后的输出没有包含它。{basis}"

    if check.get("type") == "set_no_unexpected_items":
        if unexpected:
            return (
                "错误：模型额外输出了当前 gold/alias 不接受的标签 "
                f"{unexpected}。如果这些标签只是语义接近但未命中 canonical label，"
                "这是评测标签错配；如果 source 没有直接支持，则是模型加入了 unsupported item。"
                f"{basis}"
            )
        return f"错误：模型输出集合与 source 推导出的集合不一致。{basis}"

    return f"错误：模型输出与该检查项不一致。{basis}"


def _save_run_report(task, record, trace_url: str | None) -> Path:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    scores = record.scores
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_path = RUN_ROOT / f"{task.task_id}__{record.system_name}__{timestamp}.json"
    payload = {
        "task_id": task.task_id,
        "system_name": record.system_name,
        "created_at": timestamp,
        "trace_url": trace_url,
        "task_instruction": task.instruction,
        "task_instruction_zh": TASK_INSTRUCTION_TRANSLATIONS_ZH.get(task.task_id, ""),
        "allowed_tools": task.allowed_tools,
        "sources": _source_payload(task),
        "gold_output": task.gold_output,
        "correct_solution_process": task.evaluation_criteria.scoring_notes,
        "agent_output": record.prediction.answer,
        "agent_notes": record.prediction.notes,
        "agent_tool_log": record.prediction.tool_log,
        "score": scores.model_dump() if scores else None,
        "latency_sec": record.latency_sec,
        "error": record.error,
    }
    run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_path


def _render_check_table(run: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    rows = []
    for check in checks:
        status = "pass" if check.get("correct") else "fail"
        requirement = _task_requirement_zh(run.get("task_id", ""), check.get("field", ""))
        basis = _check_basis_zh(run.get("task_id", ""), check)
        explanation = _check_explanation_zh(run.get("task_id", ""), check, basis)
        rows.append(
            "<tr>"
            f"<td><span class='pill {status}'>{'正确' if status == 'pass' else '错误'}</span></td>"
            f"<td>{_text(check.get('check_id', ''))}</td>"
            f"<td><code>{_text(check.get('expected', ''))}</code></td>"
            f"<td><code>{_text(check.get('unexpected', ''))}</code></td>"
            f"<td><code>{_text(check.get('actual', ''))}</code></td>"
            f"<td>{_text(requirement)}</td>"
            f"<td>{_text(basis)}</td>"
            f"<td>{_text(explanation)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_tool_log(tool_log: list[dict[str, Any]]) -> str:
    if not tool_log:
        return "<p class='muted'>没有记录到 tool 调用。</p>"

    chunks = []
    for index, call in enumerate(tool_log, start=1):
        result = call.get("result", "")
        chunks.append(
            "<details class='tool-call' open>"
            f"<summary>{index}. {_text(call.get('tool_name', 'unknown'))} "
            f"<code>{_text(call.get('args', {}))}</code></summary>"
            f"<pre>{_text(result)}</pre>"
            "</details>"
        )
    return "\n".join(chunks)


def _render_sources(sources: list[dict[str, str]]) -> str:
    chunks = []
    for source in sources:
        chunks.append(
            "<details class='source-block'>"
            f"<summary>{_text(source['source_id'])} <code>{_text(source['path'])}</code></summary>"
            f"<pre>{_text(source['content'])}</pre>"
            "</details>"
        )
    return "\n".join(chunks)


def _render_failure_issues(failures: list[dict[str, Any]]) -> str:
    if not failures:
        return "<p>本次没有字段级输出错误；所有原子检查都通过。</p>"

    items = []
    for failure in failures:
        items.append(
            "<li>"
            f"<strong>{_text(failure.get('check_id'))}</strong>: "
            f"expected <code>{_text(failure.get('expected'))}</code>, "
            f"actual <code>{_text(failure.get('actual'))}</code>"
            "</li>"
        )
    return "<ul>" + "\n".join(items) + "</ul>"


def _render_run_section(run: dict[str, Any]) -> str:
    score = run.get("score") or {}
    details = score.get("details") or {}
    checks = details.get("checks") or []
    failures = _failure_summary(type("ScoreProxy", (), {"details": details})())
    trace_url = run.get("trace_url")
    trace_line = (
        f"<p><a href='{_text(trace_url)}'>LangSmith trace</a></p>"
        if trace_url
        else "<p class='muted'>未找到 LangSmith trace URL。</p>"
    )

    return f"""
    <section id="{_text(run['created_at'])}-{_text(run['task_id'])}-{_text(run['system_name'])}">
      <h2>{_text(run['task_id'])} / {_text(run['system_name'])}</h2>
      <div class="metric-row">
        <div><span>准确率</span><strong>{_text(score.get('score_percent', 'N/A'))}%</strong></div>
        <div><span>通过检查</span><strong>{_text(details.get('correct_checks', 'N/A'))}/{_text(details.get('total_checks', 'N/A'))}</strong></div>
        <div><span>Latency</span><strong>{_text(run.get('latency_sec', 'N/A'))}s</strong></div>
      </div>

      <h3>原始 task 输入</h3>
      <h4>中文翻译</h4>
      <pre>{_text(_task_instruction_zh(run))}</pre>
      <h4>Original instruction</h4>
      <pre>{_text(run.get('task_instruction', ''))}</pre>
      <h4>Allowed tools</h4>
      <pre>{_json_block(run.get('allowed_tools', []))}</pre>
      <h4>Sources</h4>
      {_render_sources(run.get('sources', []))}

      <h3>正确解答过程</h3>
      <p>{_text(run.get('correct_solution_process', ''))}</p>
      <h4>正确 output</h4>
      <pre>{_json_block(run.get('gold_output', {}))}</pre>

      <h3>Agent 解答过程</h3>
      <p class="muted">这里记录可观测过程：LangSmith trace、tool 调用、tool 返回内容。不会展示模型隐藏推理链。</p>
      {trace_line}
      {_render_tool_log(run.get('agent_tool_log', []))}
      <h4>Agent output</h4>
      <pre>{_json_block(run.get('agent_output', {}))}</pre>

      <h3>评分明细</h3>
      <table>
        <thead><tr><th>结果</th><th>检查项</th><th>Expected</th><th>Unexpected</th><th>Actual</th><th>任务要求</th><th>依据</th><th>说明</th></tr></thead>
        <tbody>{_render_check_table(run, checks)}</tbody>
      </table>

      <h3>输出失败问题</h3>
      {_render_failure_issues(failures)}
    </section>
    """


def _render_html() -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    runs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RUN_ROOT.glob("*.json"))
    ]
    nav = "\n".join(
        f"<a href='#{_text(run['created_at'])}-{_text(run['task_id'])}-{_text(run['system_name'])}'>"
        f"<span>{_text(run['task_id'])}</span><small>{_text(run['system_name'])} · "
        f"{_text((run.get('score') or {}).get('score_percent', 'N/A'))}%</small></a>"
        for run in runs
    )
    sections = "\n".join(_render_run_section(run) for run in runs)

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CS263 Task Diagnostics</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d7dde5;
      --accent: #245bdb;
      --pass: #087443;
      --fail: #b42318;
      --code: #101828;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
    }}
    nav {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: #111827;
      color: white;
      padding: 20px 14px;
    }}
    nav h1 {{
      font-size: 16px;
      margin: 0 8px 18px;
      font-weight: 650;
    }}
    nav a {{
      display: block;
      color: white;
      text-decoration: none;
      padding: 10px 8px;
      border-radius: 6px;
      margin: 4px 0;
    }}
    nav a:hover {{ background: rgba(255,255,255,.1); }}
    nav span, nav small {{ display: block; }}
    nav small {{ color: #cbd5e1; margin-top: 3px; }}
    main {{
      padding: 28px;
      max-width: 1180px;
      width: 100%;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    h2 {{ margin: 0 0 18px; font-size: 24px; }}
    h3 {{
      border-top: 1px solid var(--line);
      padding-top: 20px;
      margin-top: 24px;
      font-size: 18px;
    }}
    h4 {{ margin-bottom: 8px; font-size: 14px; color: var(--muted); }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #f2f4f7;
      border: 1px solid #e4e7ec;
      color: var(--code);
      padding: 12px;
      border-radius: 6px;
      overflow: auto;
      line-height: 1.45;
    }}
    code {{
      background: #eef2ff;
      padding: 1px 4px;
      border-radius: 4px;
      word-break: break-word;
    }}
    .metric-row {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 8px;
    }}
    .metric-row div {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .metric-row span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .metric-row strong {{ font-size: 22px; }}
    details {{
      border: 1px solid var(--line);
      border-radius: 6px;
      margin: 10px 0;
      background: #fbfcfe;
    }}
    summary {{
      cursor: pointer;
      padding: 10px 12px;
      font-weight: 600;
    }}
    details pre {{
      margin: 0;
      border: 0;
      border-top: 1px solid var(--line);
      border-radius: 0 0 6px 6px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      table-layout: fixed;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 8px;
      vertical-align: top;
      word-break: break-word;
    }}
    th {{ background: #f2f4f7; text-align: left; }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
    }}
    .pill.pass {{ background: var(--pass); }}
    .pill.fail {{ background: var(--fail); }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 860px) {{
      .layout {{ grid-template-columns: 1fr; }}
      nav {{ position: relative; height: auto; }}
      main {{ padding: 16px; }}
      .metric-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <nav>
      <h1>Task Diagnostics</h1>
      {nav}
    </nav>
    <main>
      {sections}
    </main>
  </div>
</body>
</html>
"""
    HTML_PATH.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", choices=list_hard_task_ids(), required=True)
    parser.add_argument(
        "--system",
        choices=["large_single", "small_single", "small_workflow"],
        default="large_single",
    )
    args = parser.parse_args()

    task = load_hard_task(args.task_id)
    started_at = datetime.now(timezone.utc)
    record = _run_system(task, args.system)
    if not record.error:
        record.scores = score_prediction(task, record.prediction.answer)
    trace_url = _find_langsmith_trace_url(task.task_id, record.system_name, started_at)

    run_path = _save_run_report(task, record, trace_url)
    _render_html()

    print(
        json.dumps(
            {
                "run_json": str(run_path.relative_to(PROJECT_ROOT)),
                "html_report": str(HTML_PATH.relative_to(PROJECT_ROOT)),
                "task_id": task.task_id,
                "system_name": record.system_name,
                "score_percent": record.scores.score_percent if record.scores else None,
                "trace_url": trace_url,
                "error": record.error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
