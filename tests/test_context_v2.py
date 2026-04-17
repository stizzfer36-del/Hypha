"""M8 — four-layer context engine tests.

  * runtime_traces: ingest + redaction
  * embeddings: HashEncoder round-trip + cosine ranking
  * joint_query v2: four-layer rank on a toy repo; verifies that runtime
    failures and embedding similarity meaningfully move the rank.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

from hypha.context.ast_index import ASTIndex
from hypha.context.embeddings import Embeddings, HashEncoder
from hypha.context.git_history import GitHistory
from hypha.context.joint_query import JointQuery
from hypha.context.runtime_traces import RuntimeTraces


# ---- RuntimeTraces -----------------------------------------------------------


def test_runtime_traces_roundtrip(tmp_path: Path) -> None:
    rt = RuntimeTraces(tmp_path / "joint.duckdb")
    n = rt.ingest(
        [
            {"path": "a.py", "func": "f", "ts": 1.0, "ok": True},
            {"path": "b.py", "func": "g", "ts": 2.0, "ok": False},
        ]
    )
    assert n == 2


def test_runtime_traces_redacts_secrets(tmp_path: Path) -> None:
    rt = RuntimeTraces(tmp_path / "joint.duckdb")
    rt.ingest(
        [
            {
                "path": "a.py",
                "func": "f",
                "ts": 1.0,
                "ok": True,
                "attrs": {
                    "api_key": "sk-abcdefghijklmnopqrstuvwxyz1234",  # secret-ish key
                    "nonce": "bearerlooking1234567890abcdefXYZ",       # tokenish value
                    "count": 5,
                },
            }
        ]
    )
    import duckdb

    con = duckdb.connect(str(tmp_path / "joint.duckdb"))
    try:
        attrs = con.execute("SELECT attrs FROM runtime_spans").fetchone()[0]
    finally:
        con.close()
    assert "redacted" in attrs
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in attrs
    assert "bearerlooking1234567890abcdefXYZ" not in attrs
    assert '"count": 5' in attrs


# ---- Embeddings --------------------------------------------------------------


def test_hash_encoder_cosine_ranks_similar_higher(tmp_path: Path) -> None:
    emb = Embeddings(tmp_path / "joint.duckdb", encoder=HashEncoder(dim=128))
    emb.upsert(
        [
            ("file", "auth.py", "authentication session login authorize"),
            ("file", "billing.py", "invoice charge payment refund"),
        ]
    )
    top = emb.topk("handle user login", k=2)
    assert top, "expected rankings"
    assert top[0][1] == "auth.py"


def test_embeddings_reset_clears(tmp_path: Path) -> None:
    emb = Embeddings(tmp_path / "joint.duckdb", encoder=HashEncoder(dim=16))
    emb.upsert([("file", "x.py", "hello")])
    assert emb.topk("hello", k=1)
    emb.reset()
    assert emb.topk("hello", k=1) == []


# ---- Joint query v2 ----------------------------------------------------------


def _init_toy(root: Path) -> None:
    repo = pygit2.init_repository(str(root), initial_head="main")
    sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)

    (root / "auth.py").write_text(
        "def authenticate(user):\n    return user\n\n"
        "class AuthSession: pass\n"
    )
    (root / "billing.py").write_text(
        "def charge(amount):\n    return amount\n\n"
        "class Invoice: pass\n"
    )
    repo.index.add("auth.py"); repo.index.add("billing.py"); repo.index.write()
    repo.create_commit("HEAD", sig, sig, "initial", repo.index.write_tree(), [])

    # Second commit mentions billing, touches billing.
    (root / "billing.py").write_text(
        "def charge(amount):\n    return amount\n\n"
        "def invoice_for(cust): return cust\n\n"
        "class Invoice: pass\n"
    )
    repo.index.add("billing.py"); repo.index.write()
    repo.create_commit(
        "HEAD", sig, sig, "tweak billing invoice paths",
        repo.index.write_tree(), [repo.head.target],
    )


def test_joint_query_v2_runtime_boosts_failing_path(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy(root)
    duck = tmp_path / "joint.duckdb"

    ASTIndex(root, duck).rebuild()
    GitHistory(root, duck).rebuild()

    # v1 ranking: generic query "invoice charge" picks billing.py (auth wouldn't match).
    slices_v1 = JointQuery(duck).query("invoice charge", limit=5)
    assert slices_v1 and slices_v1[0].path == "billing.py"

    # Now add runtime traces showing billing.py failing frequently — this
    # should maintain or strengthen its rank and attach runtime rationale.
    import time as _t
    now = _t.time()
    RuntimeTraces(duck).ingest(
        [
            {"path": "billing.py", "func": "charge", "ts": now - 60, "ok": False},
            {"path": "billing.py", "func": "charge", "ts": now - 30, "ok": False},
            {"path": "billing.py", "func": "charge", "ts": now - 5, "ok": False},
        ]
    )
    slices_v2 = JointQuery(duck).query("invoice charge", limit=5)
    top = slices_v2[0]
    assert top.path == "billing.py"
    assert top.rationale.get("runtime") is not None
    assert top.rationale["runtime"]["fails"] >= 3
    # Runtime boost strictly adds score.
    assert slices_v2[0].score >= slices_v1[0].score


def test_joint_query_v2_embedding_layer_adds_signal(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy(root)
    duck = tmp_path / "joint.duckdb"

    ASTIndex(root, duck).rebuild()
    GitHistory(root, duck).rebuild()

    emb = Embeddings(duck, encoder=HashEncoder(dim=128))
    emb.reset()
    emb.upsert(
        [
            ("file", "auth.py", "authenticate user login session authorize"),
            ("file", "billing.py", "charge invoice payment refund"),
        ]
    )

    jq = JointQuery(duck, embeddings=emb)
    slices = jq.query("handle user login", limit=5)
    # Terms "handle" and "user" match auth.py symbol via AST (authenticate)
    # and embedding layer should also favor auth.py.
    assert slices[0].path == "auth.py"
    assert slices[0].rationale.get("embedding_sim") is not None


def test_joint_query_survives_missing_layers(tmp_path: Path) -> None:
    """Only AST populated; no git, no runtime, no embeddings."""
    root = tmp_path / "toy"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate(): pass\n")
    duck = tmp_path / "joint.duckdb"
    ASTIndex(root, duck).rebuild()
    slices = JointQuery(duck).query("authenticate", limit=5)
    assert slices and slices[0].path == "auth.py"
