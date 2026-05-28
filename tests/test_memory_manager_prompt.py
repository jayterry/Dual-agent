"""Memory Manager 提示詞：JSON 大括號不得觸發 format spec 錯誤。"""

from langchain_core.prompts import ChatPromptTemplate


def test_memory_human_template_formats_json_braces() -> None:
    """與 memory_manager.llm 相同：變數注入，勿 f-string 嵌入 JSON。"""
    human_template = (
        "已知 user_facts（JSON）：\n{known_facts_json}\n\n"
        "使用者訊息：\n{user_text}"
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "常見同義詞：{alias_hint}"),
            ("human", human_template),
        ]
    )
    msgs = prompt.format_messages(
        alias_hint="哥哥、媽媽",
        known_facts_json='{"媽媽": ["mei"]}',
        user_text="他說要殺了我",
    )
    human = msgs[-1].content
    assert "mei" in human
    assert "他說要殺了我" in human
    assert "{媽媽" not in human or '"mei"' in human
