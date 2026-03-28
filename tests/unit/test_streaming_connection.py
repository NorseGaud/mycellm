"""Tests for streaming inference over PeerConnection."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from mycellm.transport.connection import PeerConnection, PeerState
from mycellm.protocol.envelope import MessageEnvelope, MessageType


def _make_conn():
    """Create a PeerConnection with mocked protocol."""
    protocol = MagicMock()
    protocol.send_message = AsyncMock()
    conn = PeerConnection(
        peer_id="test_peer_00000000000000000000",
        protocol=protocol,
        hello=MagicMock(),
        state=PeerState.ROUTABLE,
    )
    return conn


def test_handle_response_with_future():
    """Single-response path: handle_response resolves a Future."""
    conn = _make_conn()
    loop = asyncio.new_event_loop()
    fut = loop.create_future()
    conn._pending_responses["req1"] = fut

    resp = MessageEnvelope(type=MessageType.INFERENCE_RESP, from_peer="p2", id="req1", payload={"text": "hi"})
    assert conn.handle_response(resp) is True
    assert fut.result() == resp
    loop.close()


def test_handle_response_with_queue():
    """Streaming path: handle_response puts message on Queue."""
    conn = _make_conn()
    q = asyncio.Queue()
    conn._pending_responses["req2"] = q

    chunk = MessageEnvelope(type=MessageType.INFERENCE_STREAM, from_peer="p2", id="req2", payload={"text": "token"})
    assert conn.handle_response(chunk) is True
    assert q.qsize() == 1
    assert q.get_nowait() == chunk


def test_handle_response_queue_multiple_chunks():
    """Streaming path handles multiple chunks in sequence."""
    conn = _make_conn()
    q = asyncio.Queue()
    conn._pending_responses["req3"] = q

    for i in range(5):
        chunk = MessageEnvelope(type=MessageType.INFERENCE_STREAM, from_peer="p2", id="req3", payload={"text": f"tok{i}"})
        conn.handle_response(chunk)

    assert q.qsize() == 5


@pytest.mark.asyncio
async def test_request_stream_yields_chunks():
    """request_stream should yield INFERENCE_STREAM messages until INFERENCE_DONE."""
    conn = _make_conn()

    # Simulate peer sending 3 chunks then DONE
    async def feed_responses():
        await asyncio.sleep(0.05)
        q = conn._pending_responses.get("test-req")
        for i in range(3):
            chunk = MessageEnvelope(
                type=MessageType.INFERENCE_STREAM, from_peer="p2", id="test-req",
                payload={"text": f"word{i}"},
            )
            q.put_nowait(chunk)
        done = MessageEnvelope(type=MessageType.INFERENCE_DONE, from_peer="p2", id="test-req", payload={})
        q.put_nowait(done)

    req_msg = MessageEnvelope(type=MessageType.INFERENCE_REQ, from_peer="p1", id="test-req", payload={})

    # Start feeder in background
    feeder = asyncio.create_task(feed_responses())

    chunks = []
    async for resp in conn.request_stream(req_msg, timeout=5.0):
        chunks.append(resp.payload["text"])

    await feeder
    assert chunks == ["word0", "word1", "word2"]
    assert conn._active_requests == 0
    assert "test-req" not in conn._pending_responses


@pytest.mark.asyncio
async def test_request_stream_raises_on_error():
    """request_stream should raise on ERROR message from peer."""
    conn = _make_conn()

    async def feed_error():
        await asyncio.sleep(0.05)
        q = conn._pending_responses.get("err-req")
        err = MessageEnvelope(
            type=MessageType.ERROR, from_peer="p2", id="err-req",
            payload={"message": "model unavailable"},
        )
        q.put_nowait(err)

    req_msg = MessageEnvelope(type=MessageType.INFERENCE_REQ, from_peer="p1", id="err-req", payload={})
    feeder = asyncio.create_task(feed_error())

    with pytest.raises(RuntimeError, match="model unavailable"):
        async for _ in conn.request_stream(req_msg, timeout=5.0):
            pass

    await feeder
