import pytest

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.service import FlightService


@pytest.mark.asyncio
async def test_slash_question_returns_compact_button_first_help(tmp_path):
    service = FlightService(Settings(_env_file=None), Database(str(tmp_path / "db.sqlite")), provider=object())
    text = await service.command("telegram", "1", "/?")
    assert "항공권 감시봇" in text
    assert "바로 검색" in text
    assert "한글 / 영어 / IATA" in text
    assert "/flight search" not in text
