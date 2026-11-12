import asyncio
from viv.bus import EventBus


async def test_subscriber_receives_emitted_event():
    bus = EventBus()
    q = bus.subscribe()
    bus.emit("state", state="listening")
    evt = await asyncio.wait_for(q.get(), 1)
    assert evt["channel"] == "state" and evt["text"] == "" and evt["state"] == "listening"


async def test_unsubscribed_queue_receives_nothing():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.emit("state", state="listening")
    await asyncio.sleep(0.05)
    assert q.empty()
