"""Tests for peer exchange broadcasting and handling."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from mycellm.activity import ActivityTracker, EventType
from mycellm.protocol.capabilities import Capabilities
from mycellm.router.registry import PeerRegistry, PeerEntry
from mycellm.transport.connection import PeerConnection, PeerState
from mycellm.transport.messages import peer_exchange


def _make_node():
    """Create a minimal mock node with registry, peer_connections, and activity."""
    node = MagicMock()
    node.peer_id = "bootstrap000000000000000000000000"
    node.registry = PeerRegistry()
    node._peer_connections = {}
    node.node_registry = {}
    node.activity = ActivityTracker()
    node.peer_manager = MagicMock()
    node.peer_manager.managed_peers = {}
    return node


def _make_peer_entry(peer_id, addresses=None, models=None, state=PeerState.ROUTABLE):
    """Create a PeerEntry for testing."""
    caps = Capabilities(
        models=[MagicMock(name=m, param_count_b=7.0) for m in (models or [])],
        role="seeder",
    )
    entry = PeerEntry(
        peer_id=peer_id,
        capabilities=caps,
        state=state,
        addresses=addresses or [],
    )
    return entry


class TestBuildPeerExchangeList:
    def test_excludes_self(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        entry = _make_peer_entry(node.peer_id, ["10.0.0.1:8421"])
        node.registry._peers[node.peer_id] = entry

        # Call the method directly (it's a plain method, not async)
        result = MycellmNode._build_peer_exchange_list(node)
        assert len(result) == 0

    def test_excludes_recipient(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        peer_id = "peer_a_00000000000000000000000000"
        entry = _make_peer_entry(peer_id, ["10.0.0.2:8421"], ["qwen-7b"])
        node.registry._peers[peer_id] = entry

        result = MycellmNode._build_peer_exchange_list(node, exclude_peer_id=peer_id)
        assert len(result) == 0

    def test_includes_routable_peers_with_addresses(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        peer_a = "peer_a_00000000000000000000000000"
        peer_b = "peer_b_00000000000000000000000000"
        node.registry._peers[peer_a] = _make_peer_entry(peer_a, ["10.0.0.2:8421"], ["qwen-7b"])
        node.registry._peers[peer_b] = _make_peer_entry(peer_b, ["10.0.0.3:8421"], ["llama-3b"])

        result = MycellmNode._build_peer_exchange_list(node, exclude_peer_id=peer_a)
        assert len(result) == 1
        assert result[0]["peer_id"] == peer_b

    def test_skips_peers_without_addresses(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        peer_id = "peer_no_addr_000000000000000000"
        node.registry._peers[peer_id] = _make_peer_entry(peer_id, [], ["qwen-7b"])

        result = MycellmNode._build_peer_exchange_list(node)
        assert len(result) == 0

    def test_skips_disconnected_peers(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        peer_id = "peer_disc_0000000000000000000000"
        node.registry._peers[peer_id] = _make_peer_entry(
            peer_id, ["10.0.0.4:8421"], state=PeerState.DISCONNECTED
        )

        result = MycellmNode._build_peer_exchange_list(node)
        assert len(result) == 0

    def test_includes_node_registry_entries(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        node.node_registry["http_peer_00000000000000000000"] = {
            "status": "approved",
            "api_addr": "192.168.1.100:8420",
            "capabilities": {"role": "seeder"},
        }

        result = MycellmNode._build_peer_exchange_list(node)
        assert len(result) == 1
        assert result[0]["addresses"] == ["192.168.1.100:8421"]


class TestHandlePeerExchange:
    def test_discovers_new_peers(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        msg = peer_exchange("remote_bootstrap", [
            {
                "peer_id": "new_peer_0000000000000000000000",
                "addresses": ["10.0.0.5:8421"],
                "capabilities": {"role": "seeder", "models": []},
            }
        ])

        MycellmNode._handle_peer_exchange(node, msg)

        # Should register in registry
        assert "new_peer_0000000000000000000000" in node.registry._peers

        # Should call add_peer with peer_id for dedup
        node.peer_manager.add_peer.assert_called_once_with("10.0.0.5", 8421, peer_id="new_peer_0000000000000000000000")

    def test_skips_self(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        msg = peer_exchange("remote_bootstrap", [
            {
                "peer_id": node.peer_id,
                "addresses": ["10.0.0.1:8421"],
                "capabilities": {},
            }
        ])

        MycellmNode._handle_peer_exchange(node, msg)
        node.peer_manager.add_peer.assert_not_called()

    def test_records_activity_event(self):
        from mycellm.node import MycellmNode
        node = _make_node()

        msg = peer_exchange("remote_bootstrap_00000000000000", [
            {
                "peer_id": "disc_peer_0000000000000000000000",
                "addresses": ["10.0.0.6:8421"],
                "capabilities": {},
            }
        ])

        MycellmNode._handle_peer_exchange(node, msg)

        events = node.activity.recent(event_type="peer_exchange_received")
        assert len(events) == 1
        assert events[0]["peers_discovered"] == 1


class TestPeerManagerDedup:
    def test_add_peer_skips_already_connected_peer_id(self):
        from mycellm.transport.peer_manager import PeerManager, ManagedPeer, PeerConnectionState
        node = MagicMock()
        pm = PeerManager(node)
        pm._running = True

        # Existing peer already connected via different address
        existing = ManagedPeer("10.0.0.1", 8421)
        existing.peer_id = "peer_abc"
        existing.state = PeerConnectionState.ROUTABLE
        pm._managed_peers["10.0.0.1:8421"] = existing

        # Try adding same peer_id at different address
        pm.add_peer("10.0.0.2", 8421, peer_id="peer_abc")
        assert "10.0.0.2:8421" not in pm._managed_peers

    @pytest.mark.asyncio
    async def test_add_peer_allows_different_peer_id(self):
        from mycellm.transport.peer_manager import PeerManager, ManagedPeer, PeerConnectionState
        node = MagicMock()
        pm = PeerManager(node)
        pm._running = True

        existing = ManagedPeer("10.0.0.1", 8421)
        existing.peer_id = "peer_abc"
        existing.state = PeerConnectionState.ROUTABLE
        pm._managed_peers["10.0.0.1:8421"] = existing

        # Different peer_id — should be allowed (creates task, cancel it)
        pm.add_peer("10.0.0.2", 8421, peer_id="peer_xyz")
        assert "10.0.0.2:8421" in pm._managed_peers
        # Clean up async tasks
        for t in pm._tasks:
            t.cancel()

    @pytest.mark.asyncio
    async def test_add_peer_allows_same_peer_id_if_disconnected(self):
        from mycellm.transport.peer_manager import PeerManager, ManagedPeer, PeerConnectionState
        node = MagicMock()
        pm = PeerManager(node)
        pm._running = True

        existing = ManagedPeer("10.0.0.1", 8421)
        existing.peer_id = "peer_abc"
        existing.state = PeerConnectionState.DISCONNECTED
        pm._managed_peers["10.0.0.1:8421"] = existing

        # Same peer_id but existing is disconnected — allow retry on new address
        pm.add_peer("10.0.0.2", 8421, peer_id="peer_abc")
        assert "10.0.0.2:8421" in pm._managed_peers
        for t in pm._tasks:
            t.cancel()
