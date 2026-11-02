"""In-process WebSocket notification fan-out (Phase 7; FR-48)."""

from __future__ import annotations

import asyncio
import threading

from app.services.event_broadcaster import EventBroadcaster


def test_publish_is_noop_without_loop_or_subscribers() -> None:
    broadcaster = EventBroadcaster()
    broadcaster.publish({"type": "event"})  # no loop bound: must not raise
    broadcaster.bind_loop(asyncio.new_event_loop())
    broadcaster.publish({"type": "event"})  # no subscribers: must not raise


def test_subscribers_receive_published_messages() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        first = broadcaster.subscribe()
        second = broadcaster.subscribe()

        broadcaster.publish({"type": "event", "event": {"id": 1}})
        await asyncio.sleep(0)

        assert broadcaster.subscriber_count == 2
        assert await first.get() == {"type": "event", "event": {"id": 1}}
        assert await second.get() == {"type": "event", "event": {"id": 1}}

        broadcaster.unsubscribe(first)
        broadcaster.unsubscribe(second)
        assert broadcaster.subscriber_count == 0

    asyncio.run(scenario())


def test_slow_subscriber_queue_is_bounded() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster(queue_maxsize=1)
        broadcaster.bind_loop(asyncio.get_running_loop())
        queue = broadcaster.subscribe()

        broadcaster.publish({"n": 1})
        broadcaster.publish({"n": 2})
        await asyncio.sleep(0)

        # The oldest notification is dropped rather than growing memory without bound.
        assert await queue.get() == {"n": 2}

    asyncio.run(scenario())


def test_publish_from_another_thread_delivers() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        queue = broadcaster.subscribe()

        worker = threading.Thread(target=broadcaster.publish, args=({"type": "event"},))
        worker.start()
        worker.join()

        message = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert message == {"type": "event"}

    asyncio.run(scenario())


def test_a_stuck_subscriber_does_not_block_another_subscriber() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster(queue_maxsize=1)
        broadcaster.bind_loop(asyncio.get_running_loop())
        stuck = broadcaster.subscribe()
        fresh = broadcaster.subscribe()

        broadcaster.publish({"n": 1})
        broadcaster.publish({"n": 2})
        await asyncio.sleep(0)

        # Each subscriber has its own bounded queue: the newest survives on both.
        assert await stuck.get() == {"n": 2}
        assert await fresh.get() == {"n": 2}

    asyncio.run(scenario())


def test_concurrent_publishers_reach_every_subscriber() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        subscribers = [broadcaster.subscribe() for _ in range(5)]
        batch = list(range(20))
        publishers_count = 3
        total = len(batch) * publishers_count

        def publish_batch() -> None:
            for value in batch:
                broadcaster.publish({"n": value})

        publishers = [threading.Thread(target=publish_batch) for _ in range(publishers_count)]
        for publisher in publishers:
            publisher.start()
        for publisher in publishers:
            publisher.join()

        # Let the cross-thread ``call_soon_threadsafe`` callbacks run on this loop.
        for _ in range(200):
            if all(queue.qsize() == total for queue in subscribers):
                break
            await asyncio.sleep(0)

        expected = sorted(batch * publishers_count)
        for queue in subscribers:
            received = sorted([(await queue.get())["n"] for _ in range(total)])
            assert received == expected

    asyncio.run(scenario())
