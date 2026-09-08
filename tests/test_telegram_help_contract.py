from flight_bot.service import HELP


def test_help_is_compact_button_first_and_hides_legacy_commands():
    assert "감시 등록" in HELP
    assert "바로 검색" in HELP
    assert "내 슬롯" in HELP
    assert "채팅방마다" in HELP
    assert "20개" in HELP
    assert "한글 / 영어 / IATA" in HELP
    assert "/flight" not in HELP
    assert "/?" not in HELP
