from loopengine import skills


def test_constitution_has_money_clause():
    text = skills.constitution()
    assert "§1" in text
    assert "Decimal" in text


def test_prompt_loads_actor_template_with_placeholders():
    text = skills.prompt("actor")
    assert "{spec}" in text
    assert "{last_error}" in text


def test_critic_prompts_request_json_verdict():
    assert '"verdict"' in skills.prompt("qa_critic")
    assert '"verdict"' in skills.prompt("security_critic")
