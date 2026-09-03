import asyncio

import pytest

from flight_bot.providers import ProviderError, RoundRobinKeyPool


@pytest.mark.asyncio
async def test_round_robin_cycles_in_order():
    pool = RoundRobinKeyPool(["k1", "k2", "k3"])

    actual = [await pool.next_key() for _ in range(7)]

    assert actual == ["k1", "k2", "k3", "k1", "k2", "k3", "k1"]


@pytest.mark.asyncio
async def test_single_key_is_reused():
    pool = RoundRobinKeyPool(["only"])

    assert [await pool.next_key() for _ in range(3)] == ["only", "only", "only"]


@pytest.mark.asyncio
async def test_concurrent_requests_allocate_evenly():
    pool = RoundRobinKeyPool(["k1", "k2", "k3"])

    actual = await asyncio.gather(*(pool.next_key() for _ in range(6)))

    assert actual.count("k1") == 2
    assert actual.count("k2") == 2
    assert actual.count("k3") == 2


@pytest.mark.asyncio
async def test_empty_pool_fails_closed():
    pool = RoundRobinKeyPool([])

    with pytest.raises(ProviderError):
        await pool.next_key()
