"""端到端編排。"""



from __future__ import annotations



from dual_agent.dai.fraud_dual.gnn import assemble_result_a, score_context

from dual_agent.dai.fraud_dual.llm import OllamaError, run_path_b

from dual_agent.dai.fraud_dual.ml import predict_threat

from dual_agent.dai.fraud_dual.shared.features import extract_shared

from dual_agent.dai.fraud_dual.shared.schemas import AnalyzeRequest, AnalyzeResponse, BuildGraphInput, ResultB





def run_pipeline(request: AnalyzeRequest) -> AnalyzeResponse:

    """

    Phase 4：共享特徵 + ML Threat + Context → Result_A；

    可選 Path B（Ollama，不讀 A 分數）。

    Narrator 尚未接通。

    """

    build = BuildGraphInput(

        age_band=request.age_band,

        occupation=request.occupation,

        relation_type=request.relation_type,

        channel=request.channel,

        primary_apps=request.primary_apps,

        invest_exp=request.invest_exp,

    )

    shared = extract_shared(request.text, build)

    threat, writeback = predict_threat(shared)

    graph, ctx = score_context(shared, writeback, backend="auto")

    result_a = assemble_result_a(
        threat,
        ctx.context_score,
        backend=ctx.backend,
        factors=list(ctx.factors or []),
    )



    result_b: ResultB | None = None

    path_b_note = "Path B skipped"

    if request.include_path_b:

        try:

            # 刻意只傳 shared + build；不傳 result_a / threat / writeback

            result_b = run_path_b(shared, build)

            path_b_note = "Path B ok (Ollama)"

        except OllamaError as e:

            path_b_note = f"Path B failed: {e}"

        except (ValueError, TypeError) as e:

            path_b_note = f"Path B parse/input error: {e}"



    factors = ",".join(ctx.factors) if ctx.factors else "none"

    phase = "4" if result_b is not None else "3"

    status = "ok" if result_b is not None else "partial"

    narrator_note = "Narrator not wired."

    if request.include_narrator:

        narrator_note = "Narrator requested but not wired."



    return AnalyzeResponse(

        shared_features=shared,

        threat=threat,

        graph_writeback=writeback,

        result_a=result_a,

        result_b=result_b,

        narrator_text=None,

        phase=phase,

        status=status,

        detail=(

            f"Phase {phase}: Result_A ready (context_backend={ctx.backend}; "

            f"factors={factors}). {path_b_note}. "

            f"Graph nodes={len(graph.nodes)} edges={len(graph.edges)}. "

            f"{narrator_note}"

        ),

    )


