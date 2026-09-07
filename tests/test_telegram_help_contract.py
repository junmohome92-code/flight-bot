from flight_bot.service import HELP


def test_help_includes_slash_question_alias_and_button_capabilities():
    assert "/?" in HELP
    assert "최대 20개 슬롯" in HELP
    assert "바로 검색" in HELP
    assert "지금 검색" in HELP
