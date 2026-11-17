"""Regression: Agent Runtime runs each query on a new event loop; the Toolbox client must not outlive its loop."""
import asyncio

from google.adk.tools.base_toolset import BaseToolset

from heat_dispatch.toolbox import LoopSafeToolboxToolset


class LoopBoundToolset(BaseToolset):
    """Behaves like ToolboxToolset: usable only on the loop it was first used on."""

    def __init__(self):
        super().__init__()
        self.loop = None

    async def get_tools(self, readonly_context=None):
        cur = asyncio.get_running_loop()
        self.loop = self.loop or cur
        if self.loop is not cur or self.loop.is_closed():
            raise RuntimeError("Event loop is closed")
        return ["tool"]

    async def close(self):
        pass


def test_plain_toolset_breaks_on_the_second_loop_but_the_wrapper_does_not():
    plain = LoopBoundToolset()
    assert asyncio.run(plain.get_tools()) == ["tool"]
    try:
        asyncio.run(plain.get_tools())
        raise AssertionError("expected the plain toolset to fail on a new loop")
    except RuntimeError as exc:
        assert "Event loop is closed" in str(exc)

    made = []
    safe = LoopSafeToolboxToolset(lambda: made.append(LoopBoundToolset()) or made[-1])
    for _ in range(3):                                   # three queries, three event loops
        assert asyncio.run(safe.get_tools()) == ["tool"]
    assert len(made) == 3 and len(safe._by_loop) == 1    # closed loops are pruned, no leak


def test_same_loop_reuses_one_client():
    made = []
    safe = LoopSafeToolboxToolset(lambda: made.append(LoopBoundToolset()) or made[-1])

    async def many():
        for _ in range(5):
            await safe.get_tools()
    asyncio.run(many())
    assert len(made) == 1
