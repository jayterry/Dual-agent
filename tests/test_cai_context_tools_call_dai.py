"""固定多輪問答回歸：ask_user -> call_dai -> follow-up。"""

from __future__ import annotations

from desktop_cai_app import _build_memory_assistant_text
from dual_agent.cai.context_layer import SessionMemory, build_plan_summary, pack_context, record_turn
from dual_agent.cai.executor import format_results_for_display
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.schemas import PlanExecuteOutcome, PlanStep, PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext, SkillResult

import dual_agent.cai.plan_execute as plan_execute


def _record_desktop_style_turn(
    session: SessionMemory,
    *,
    user_text: str,
    outcome: PlanExecuteOutcome,
) -> str:
    assistant = _build_memory_assistant_text(outcome.answer, outcome.results)
    result_summary = format_results_for_display(outcome.results) if outcome.results else "（本輪無 Executor 結果）"
    record_turn(
        session,
        user=user_text,
        assistant=assistant,
        task_type=outcome.task_type,
        task_state=outcome.task_state,
        model="fake",
        base_url="http://127.0.0.1:11434",
        plan_summary=build_plan_summary(outcome.plan),
        result_summary=result_summary,
    )
    return assistant


def test_multi_turn_review_regression_keeps_memory_clean_for_followup(monkeypatch) -> None:
    session = SessionMemory()
    ctx = SkillContext(user_input="")
    captured: dict[str, str] = {}
    executed: list[object] = []

    def fake_invoke_planner(
        *,
        user_text: str,
        source_turn_text: str | None = None,
        tool_catalog: list[dict[str, object]],
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        ingress_summary: str | None = None,
        ingress_detected_task_type: str = "",
        ingress_artifact_text: str = "",
        pending_review: bool = False,
        task_snapshot: dict | None = None,
        ingress_requires_dai: bool = False,
        review_pending_candidate: bool = False,
    ) -> PlannerOutput:
        assert tool_catalog
        if "有人發簡訊給我" in user_text:
            assert pending_review is False
            return PlannerOutput(task_type="check", task_state="new", todos=[], message="")
        if "3000萬" in user_text and "殺" in user_text:
            art = (ingress_artifact_text or "").strip()
            assert art
            assert pending_review is True
            return PlannerOutput(
                task_type="check",
                task_state="running",
                todos=[
                    PlanStep(
                        skill="call_dai",
                        args={
                            "artifact": art,
                            "user_text": user_text.strip()[:240],
                            "context_pack": "",
                            "sms_review": True,
                        },
                    )
                ],
                message="",
            )
        assert user_text == "我現在該怎麼辦?"
        assert source_turn_text == "我現在該怎麼辦?"
        assert ingress_detected_task_type == "unknown"
        assert ingress_artifact_text == ""
        assert pending_review is False
        cp = context_pack or ""
        captured["planner_context_pack"] = cp
        assert "【DAI 風險摘要】" in cp
        assert "風險分數：95/100" in cp
        assert "高風險勒索訊息" in cp
        assert '"context_pack": "（已省略）"' in cp
        assert "計畫步驟數：" not in cp
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="依前文回答。")

    def fake_execute_step(step: object, ctx: SkillContext) -> SkillResult:
        skill = getattr(step, "skill", "")
        if skill != "call_dai":
            from dual_agent.cai.executor import execute_step as real_execute_step

            return real_execute_step(step, ctx)
        executed.append(step)
        ctx.policy_state.pop("pending_review", None)
        args = getattr(step, "args", {})
        assert "3000萬" in str(args.get("artifact") or "")
        assert args.get("sms_review") is True
        return SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 95/100；高風險勒索",
            data={
                "dai": {
                    "risk_score": 95,
                    "recommended_cai_action": "block",
                    "safety_summary": "高風險勒索訊息",
                    "reason_highlights": ["要求支付 3000 萬", "包含人身威脅"],
                }
            },
        )

    def fake_invoke_replan(
        *,
        user_text: str,
        task_type: str,
        task_state: str,
        remaining_todos: list[object],
        observation_log: str | None,
        planner_message: str,
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        pending_review: bool = False,
    ) -> ReplanOutput:
        if "有人發簡訊給我" in user_text and observation_log and "ask_user" in observation_log:
            assert task_type == "check"
            return ReplanOutput(
                complete=True,
                final_answer=(
                    "請貼上完整簡訊或訊息內容，我才能幫您進一步審查。"
                    "若您本人或家人有立即危險，請先聯絡警方或當地緊急單位。"
                ),
                updated_todos=[],
                task_state="waiting_input",
                waiting_input=False,
                user_prompt="",
            )
        if "3000萬" in user_text:
            assert task_type == "check"
            assert task_state == "running"
            assert pending_review is True
            assert "call_dai" in (observation_log or "")
            assert "風險分數：95/100" in (observation_log or "")
            return ReplanOutput(
                complete=True,
                final_answer="這是高風險勒索訊息。風險分數 95/100，請先報警，不要付款。",
                updated_todos=[],
                task_state="completed",
                waiting_input=False,
                user_prompt="",
            )

        assert user_text == "我現在該怎麼辦?"
        assert task_type == "direct_response"
        assert task_state == "answering"
        assert pending_review is False
        captured["replan_context_pack"] = context_pack or ""
        assert captured["replan_context_pack"] == captured["planner_context_pack"]
        assert planner_message == "依前文回答。"
        return ReplanOutput(
            complete=True,
            final_answer="請先聯絡警方與家人確認安全，保留訊息證據，不要付款。",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    monkeypatch.setattr(plan_execute, "invoke_planner", fake_invoke_planner)
    monkeypatch.setattr(plan_execute, "execute_step", fake_execute_step)
    monkeypatch.setattr(plan_execute, "invoke_replan", fake_invoke_replan)

    turn1 = "有人發簡訊給我"
    out1 = run_plan_and_execute(user_text=turn1, ctx=ctx, context_pack=pack_context(session))
    assert out1.task_type == "check"
    assert out1.task_state == "waiting_input"
    assert len(out1.plan) == 1
    assert out1.plan[0].skill == "ask_user"
    assert "請貼上完整簡訊或訊息內容" in out1.answer
    assert ctx.policy_state.get("pending_review")
    _record_desktop_style_turn(session, user_text=turn1, outcome=out1)

    turn2 = "他說要我給她3000萬 不然就殺了我"
    out2 = run_plan_and_execute(user_text=turn2, ctx=ctx, context_pack=pack_context(session))
    assert len(executed) == 1
    assert out2.task_type == "check"
    assert out2.task_state == "completed"
    assert out2.plan[0].skill == "call_dai"
    assert "風險分數 95/100" in out2.answer
    assert not ctx.policy_state.get("pending_review")
    assistant_turn2 = _record_desktop_style_turn(session, user_text=turn2, outcome=out2)
    assert "【DAI 風險摘要】" in assistant_turn2
    assert "計畫步驟數：" not in assistant_turn2

    turn3 = "我現在該怎麼辦?"
    out3 = run_plan_and_execute(user_text=turn3, ctx=ctx, context_pack=pack_context(session))
    assert out3.task_type == "direct_response"
    assert out3.task_state == "completed"
    assert out3.answer == "請先聯絡警方與家人確認安全，保留訊息證據，不要付款。"


def test_recorded_call_dai_turn_feeds_clean_context_pack() -> None:
    session = SessionMemory()
    outcome = PlanExecuteOutcome(
        plan=[
            plan_execute.PlanStep(
                skill="call_dai",
                args={
                    "artifact": "你男友在我手上，給我500萬",
                    "user_text": "請審查這則威脅訊息",
                    "context_pack": "【最近對話緩衝】很長很長的內容",
                    "sms_review": True,
                },
            )
        ],
        results=[
            SkillResult(
                ok=True,
                skill="call_dai",
                summary="[DAI] 風險分數 88/100；高風險",
                data={
                    "dai": {
                        "risk_score": 88,
                        "recommended_cai_action": "block",
                        "safety_summary": "高風險威脅訊息",
                        "reason_highlights": ["要求支付大額金錢"],
                    }
                },
            )
        ],
        answer="請立即報警並保留證據。",
        task_type="check",
        task_state="completed",
    )

    assistant = _record_desktop_style_turn(session, user_text="他傳簡訊威脅我", outcome=outcome)
    packed = pack_context(session)

    assert "【DAI 風險摘要】" in assistant
    assert "計畫步驟數：" not in assistant
    assert "請立即報警並保留證據。" in packed
    assert "【DAI 風險摘要】" in packed
    assert '"context_pack": "（已省略）"' in packed
    assert "很長很長的內容" not in packed


def test_identity_question_prefers_latest_user_name_correction_from_context(monkeypatch) -> None:
    session = SessionMemory()
    ctx = SkillContext(user_input="")
    captured: dict[str, str] = {}

    record_turn(
        session,
        user="hello 我是terry",
        assistant="你好 Terry，我是你的助手小智。請問有什麼可以幫助你？",
        task_type="direct_response",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1:11434",
    )
    record_turn(
        session,
        user="你為甚麼叫小智",
        assistant="我是因為名字叫做智慧，所以被稱為小智。",
        task_type="direct_response",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1:11434",
    )
    record_turn(
        session,
        user="你現在叫CAI",
        assistant="目前我叫CAI，你可以這樣叫我。",
        task_type="direct_response",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1:11434",
    )

    def fake_invoke_planner(
        *,
        user_text: str,
        source_turn_text: str | None = None,
        tool_catalog: list[dict[str, object]],
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        ingress_summary: str | None = None,
        ingress_detected_task_type: str = "",
        ingress_artifact_text: str = "",
        pending_review: bool = False,
        task_snapshot: dict | None = None,
        ingress_requires_dai: bool = False,
        review_pending_candidate: bool = False,
    ) -> PlannerOutput:
        assert tool_catalog
        assert source_turn_text == "我是誰 \n你又是誰"
        assert ingress_detected_task_type == "unknown"
        assert ingress_artifact_text == ""
        assert pending_review is False
        captured["planner_context_pack"] = context_pack or ""
        assert "hello 我是terry" in captured["planner_context_pack"]
        assert "你現在叫CAI" in captured["planner_context_pack"]
        assert captured["planner_context_pack"].rfind("你現在叫CAI") > captured["planner_context_pack"].find("小智")
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="依人物脈絡回答。")

    def fake_invoke_replan(
        *,
        user_text: str,
        task_type: str,
        task_state: str,
        remaining_todos: list[object],
        observation_log: str | None,
        planner_message: str,
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        pending_review: bool = False,
    ) -> ReplanOutput:
        assert user_text == "我是誰 \n你又是誰"
        assert task_type == "direct_response"
        assert task_state == "answering"
        assert remaining_todos == []
        assert pending_review is False
        assert observation_log is None
        assert planner_message == "依人物脈絡回答。"
        cp = context_pack or ""
        assert cp == captured["planner_context_pack"]
        assert "Terry" in cp
        assert "CAI" in cp
        return ReplanOutput(
            complete=True,
            final_answer="你是 Terry，我是 CAI。",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    monkeypatch.setattr(plan_execute, "invoke_planner", fake_invoke_planner)
    monkeypatch.setattr(plan_execute, "invoke_replan", fake_invoke_replan)

    out = run_plan_and_execute(user_text="我是誰 \n你又是誰", ctx=ctx, context_pack=pack_context(session))
    assert out.task_type == "direct_response"
    assert out.task_state == "completed"
    assert out.answer == "你是 Terry，我是 CAI。"


def test_relation_name_question_prefers_newer_user_fact_from_context(monkeypatch) -> None:
    session = SessionMemory()
    ctx = SkillContext(user_input="")
    captured: dict[str, str] = {}

    record_turn(
        session,
        user="我媽媽叫 May",
        assistant="收到。",
        task_type="direct_response",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1:11434",
    )
    dai_turn = PlanExecuteOutcome(
        plan=[
            plan_execute.PlanStep(
                skill="call_dai",
                args={
                    "artifact": "要我給3000萬元，不然就殺了我媽媽mei",
                    "user_text": "請審查這則威脅訊息",
                    "context_pack": "（已省略）",
                    "sms_review": True,
                },
            )
        ],
        results=[
            SkillResult(
                ok=True,
                skill="call_dai",
                summary="[DAI] 風險分數 100/100；高風險威脅",
                data={
                    "dai": {
                        "risk_score": 100,
                        "recommended_cai_action": "ask_user",
                        "safety_summary": "該簡訊包含威脅內容，建議立即採取行動。",
                        "reason_highlights": [
                            "高風險威脅信息，涉及人身安全與金錢勒索",
                            "要我給3000萬元，不然就殺了我媽媽mei",
                        ],
                    }
                },
            )
        ],
        answer="這條簡訊包含高風險威脅內容，請立即聯絡警方並保留證據。",
        task_type="check",
        task_state="completed",
    )
    _record_desktop_style_turn(session, user_text="要我給3000萬元，不然就殺了我媽媽mei", outcome=dai_turn)

    def fake_invoke_planner(
        *,
        user_text: str,
        source_turn_text: str | None = None,
        tool_catalog: list[dict[str, object]],
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        ingress_summary: str | None = None,
        ingress_detected_task_type: str = "",
        ingress_artifact_text: str = "",
        pending_review: bool = False,
        task_snapshot: dict | None = None,
        ingress_requires_dai: bool = False,
        review_pending_candidate: bool = False,
    ) -> PlannerOutput:
        assert tool_catalog
        assert user_text == "我媽媽叫甚麼"
        assert source_turn_text == "我媽媽叫甚麼"
        assert ingress_detected_task_type == "unknown"
        assert ingress_artifact_text == ""
        assert pending_review is False
        captured["planner_context_pack"] = context_pack or ""
        assert "我媽媽叫 May" in captured["planner_context_pack"]
        assert "我媽媽mei" in captured["planner_context_pack"]
        assert captured["planner_context_pack"].rfind("我媽媽mei") > captured["planner_context_pack"].find("我媽媽叫 May")
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="依最新人物事實回答。")

    def fake_invoke_replan(
        *,
        user_text: str,
        task_type: str,
        task_state: str,
        remaining_todos: list[object],
        observation_log: str | None,
        planner_message: str,
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        pending_review: bool = False,
    ) -> ReplanOutput:
        assert user_text == "我媽媽叫甚麼"
        assert task_type == "direct_response"
        assert task_state == "answering"
        assert remaining_todos == []
        assert pending_review is False
        assert observation_log is None
        assert planner_message == "依最新人物事實回答。"
        cp = context_pack or ""
        assert cp == captured["planner_context_pack"]
        assert "May" in cp
        assert "mei" in cp
        return ReplanOutput(
            complete=True,
            final_answer="你媽媽叫 mei。",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    monkeypatch.setattr(plan_execute, "invoke_planner", fake_invoke_planner)
    monkeypatch.setattr(plan_execute, "invoke_replan", fake_invoke_replan)

    out = run_plan_and_execute(user_text="我媽媽叫甚麼", ctx=ctx, context_pack=pack_context(session))
    assert out.task_type == "direct_response"
    assert out.task_state == "completed"
    assert out.answer == "你媽媽叫 mei。"


def test_full_transcript_regression_prefers_cai_and_mei_over_older_or_generic_mentions(monkeypatch) -> None:
    session = SessionMemory()
    ctx = SkillContext(user_input="")
    captured: dict[str, str] = {}

    direct_turns = [
        ("hello 我是terry", "你好 Terry，我是你的助手小智。請問有什麼可以幫助你？"),
        ("你為甚麼叫小智", "我是因為名字叫做智慧，所以被稱為小智。有其他問題需要幫助嗎？"),
        ("你現在叫CAI", "目前我叫CAI，你可以這樣叫我。有其他問題需要幫助嗎？"),
        ("我是誰 \n你又是誰", "您好，我是CAI，你的助手。請告訴我您的名字吧。"),
        ("你不知道我是誰?", "您好 Terry，我記得你叫Terry。請告訴我更多關於你需要什麼幫助吧。"),
        ("我很害怕", "我理解您現在感到害怕。如果您願意分享更多關於原因的話，我會盡力提供幫助。"),
    ]
    for user_text, assistant_text in direct_turns:
        record_turn(
            session,
            user=user_text,
            assistant=assistant_text,
            task_type="direct_response",
            task_state="completed",
            model="fake",
            base_url="http://127.0.0.1:11434",
        )

    ask_user_turn = PlanExecuteOutcome(
        plan=[
            plan_execute.PlanStep(
                skill="ask_user",
                args={"question": "請貼上完整簡訊或訊息內容，我才能幫您審查風險。"},
            )
        ],
        results=[],
        answer="請貼上完整簡訊或訊息內容，我才能幫您進一步審查。若您本人或家人有立即危險，請先聯絡警方或當地緊急單位。",
        task_type="check",
        task_state="waiting_input",
    )
    _record_desktop_style_turn(session, user_text="有個人發簡訊威脅我", outcome=ask_user_turn)

    dai_turn = PlanExecuteOutcome(
        plan=[
            plan_execute.PlanStep(
                skill="call_dai",
                args={
                    "artifact": "要我給3000萬元，不然就殺了我媽媽mei",
                    "user_text": "請審查這則威脅訊息",
                    "context_pack": "（已省略）",
                    "sms_review": True,
                },
            )
        ],
        results=[
            SkillResult(
                ok=True,
                skill="call_dai",
                summary="[DAI] 風險分數 100/100；高風險威脅",
                data={
                    "dai": {
                        "risk_score": 100,
                        "recommended_cai_action": "ask_user",
                        "safety_summary": "該簡訊包含威脅內容，建議立即採取行動。",
                        "reason_highlights": [
                            "高風險威脅信息，涉及人身安全與金錢勒索",
                            "要我給3000萬元，不然就殺了我媽媽mei",
                            "guard_scan 判定：block",
                        ],
                    }
                },
            )
        ],
        answer="這條簡訊包含高風險威脅內容，建議您立即聯絡警方或當地緊急單位。請不要回覆該發件人，並保存此簡訊作為證據。",
        task_type="check",
        task_state="completed",
    )
    _record_desktop_style_turn(session, user_text="要我給3000萬元，不然就殺了我媽媽mei", outcome=dai_turn)

    record_turn(
        session,
        user="現在怎麼辦",
        assistant="請立即聯絡警方或當地緊急單位，並保存此簡訊作為證據。不要回覆該發件人。",
        task_type="direct_response",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1:11434",
    )
    record_turn(
        session,
        user="我媽媽是誰",
        assistant="您好 Terry，您提到的『我媽媽』是指您的母親。如果您需要更多關於家庭成員的信息或其他幫助，請告訴我具體需求。",
        task_type="direct_response",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1:11434",
    )

    def fake_invoke_planner(
        *,
        user_text: str,
        source_turn_text: str | None = None,
        tool_catalog: list[dict[str, object]],
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        ingress_summary: str | None = None,
        ingress_detected_task_type: str = "",
        ingress_artifact_text: str = "",
        pending_review: bool = False,
        task_snapshot: dict | None = None,
        ingress_requires_dai: bool = False,
        review_pending_candidate: bool = False,
    ) -> PlannerOutput:
        assert tool_catalog
        cp = context_pack or ""
        if user_text == "你又是誰":
            captured["who_context_pack"] = cp
            assert "小智" in cp
            assert "你現在叫CAI" in cp
            assert cp.rfind("你現在叫CAI") > cp.find("小智")
            return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="依人物脈絡回答。")

        assert user_text == "我媽媽叫甚麼"
        captured["mom_context_pack"] = cp
        assert "要我給3000萬元，不然就殺了我媽媽mei" in cp
        assert "『我媽媽』是指您的母親" in cp
        assert "Terry" in cp
        assert "CAI" in cp
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="依最新人物事實回答。")

    def fake_invoke_replan(
        *,
        user_text: str,
        task_type: str,
        task_state: str,
        remaining_todos: list[object],
        observation_log: str | None,
        planner_message: str,
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        pending_review: bool = False,
    ) -> ReplanOutput:
        assert task_type == "direct_response"
        assert task_state == "answering"
        assert remaining_todos == []
        assert observation_log is None
        assert pending_review is False
        cp = context_pack or ""
        if user_text == "你又是誰":
            assert cp == captured["who_context_pack"]
            assert planner_message == "依人物脈絡回答。"
            return ReplanOutput(
                complete=True,
                final_answer="我是 CAI。",
                updated_todos=[],
                task_state="completed",
                waiting_input=False,
                user_prompt="",
            )

        assert user_text == "我媽媽叫甚麼"
        assert cp == captured["mom_context_pack"]
        assert planner_message == "依最新人物事實回答。"
        return ReplanOutput(
            complete=True,
            final_answer="你媽媽叫 mei。",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    monkeypatch.setattr(plan_execute, "invoke_planner", fake_invoke_planner)
    monkeypatch.setattr(plan_execute, "invoke_replan", fake_invoke_replan)

    who_out = run_plan_and_execute(user_text="你又是誰", ctx=ctx, context_pack=pack_context(session))
    assert who_out.task_type == "direct_response"
    assert who_out.task_state == "completed"
    assert who_out.answer == "我是 CAI。"
    _record_desktop_style_turn(session, user_text="你又是誰", outcome=who_out)

    mom_out = run_plan_and_execute(user_text="我媽媽叫甚麼", ctx=ctx, context_pack=pack_context(session))
    assert mom_out.task_type == "direct_response"
    assert mom_out.task_state == "completed"
    assert mom_out.answer == "你媽媽叫 mei。"
