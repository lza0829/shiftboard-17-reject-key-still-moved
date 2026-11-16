from pathlib import Path
import os
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATA_DIR"] = str(ROOT / "backend" / "data_test_partial")
os.environ["FIXTURES_DIR"] = str(ROOT / "fixtures")


@pytest.fixture(scope="module")
def client():
    # 与 test_handover_smoke 隔离的独立库；在 fixture 内改向，避免收集期影响其他模块
    import app.db as db

    db.DATA_DIR = Path(os.environ["DATA_DIR"])
    db.DB_PATH = db.DATA_DIR / "app.db"
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    from app.main import app

    with TestClient(app) as c:
        yield c


def _raw():
    import app.db as db

    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _start(client, frm=1, to=2):
    r = client.post("/api/handovers/start", json={"from_shift_id": frm, "to_shift_id": to})
    assert r.status_code == 200, r.text
    return r.json()


def _inflight_keys(client, shift_id):
    rows = client.get("/api/batches", params={"owner_shift_id": shift_id}).json()
    return {b["biz_key"] for b in rows if b["status"] == "在途"}


def test_partial_reject_flow(client):
    started = _start(client)
    hid = started["id"]
    items = started["items"]
    assert len(items) == 4
    reject_ids = [items[0]["id"], items[2]["id"]]
    rejected_keys = {items[0]["biz_key"], items[2]["biz_key"]}
    transferred_keys = {items[1]["biz_key"], items[3]["biz_key"]}

    # 进行中拒收：选定清单键 + 原因，落独立拒收表
    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={
            "rejections": [
                {"batch_id": reject_ids[0], "reason": "单据不全"},
                {"batch_id": reject_ids[1], "reason": "半成品未核验"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["buckets"] == {"清单数": 4, "过户数": 0, "拒收数": 2}

    # 拒收记录真实落库（绕过 API 直查 SQLite），刷新后不丢
    conn = _raw()
    rows = conn.execute(
        "SELECT batch_id, reason FROM handover_rejections WHERE handover_id = ?",
        (hid,),
    ).fetchall()
    conn.close()
    assert {row["batch_id"]: row["reason"] for row in rows} == {
        reject_ids[0]: "单据不全",
        reject_ids[1]: "半成品未核验",
    }

    # 与交班单隔离可查
    got = client.get(f"/api/handovers/{hid}/rejections")
    assert got.status_code == 200
    assert {row["batch_id"] for row in got.json()} == set(reject_ids)

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "已完成"
    assert body["buckets"] == {"清单数": 4, "过户数": 2, "拒收数": 2}

    # 未拒收键过户到接班方；拒收键留在交班方在途且不得出现在接班方
    sender_keys = _inflight_keys(client, 1)
    receiver_keys = _inflight_keys(client, 2)
    assert rejected_keys <= sender_keys
    assert transferred_keys <= receiver_keys
    assert not (rejected_keys & receiver_keys)

    # 对账报告分桶与归属/拒收记录同源
    reports = client.get("/api/reconcile").json()
    rep = next(r for r in reports if r["handover_id"] == hid)
    assert rep["before_count"] == 4
    assert rep["transferred_count"] == 2
    assert rep["rejected_count"] == 2
    assert rep["一致"] is True
    assert set(rep["detail"]["拒收键"]) == rejected_keys
    assert set(rep["detail"]["过户键"]) == transferred_keys
    assert set(rep["detail"]["清单键"]) == rejected_keys | transferred_keys

    # 结案后拒收记录仍隔离可查
    assert len(client.get(f"/api/handovers/{hid}/rejections").json()) == 2


def test_reject_validation(client):
    started = _start(client)
    hid = started["id"]
    items = started["items"]
    assert len(items) == 2  # 上一单被拒收的 2 键仍在交班方在途

    # 清单外键 → 400
    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": 99999, "reason": "x"}]},
    )
    assert r.status_code == 400
    # 空原因 → 400
    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": items[0]["id"], "reason": "  "}]},
    )
    assert r.status_code == 400
    # 重复拒收同一键 → 400
    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={
            "rejections": [
                {"batch_id": items[0]["id"], "reason": "a"},
                {"batch_id": items[0]["id"], "reason": "b"},
            ]
        },
    )
    assert r.status_code == 400
    # 勾选后取消（整体替换为空集）
    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": items[0]["id"], "reason": "包装破损"}]},
    )
    assert r.status_code == 200
    r = client.put(f"/api/handovers/{hid}/rejections", json={"rejections": []})
    assert r.status_code == 200
    assert client.get(f"/api/handovers/{hid}/rejections").json() == []

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.json()["status"] == "已完成"
    # 结案后拒收标记不可再改
    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": items[0]["id"], "reason": "太晚"}]},
    )
    assert r.status_code == 400


def test_completion_failure_rolls_back(client):
    started = _start(client, frm=2, to=3)
    hid = started["id"]
    items = started["items"]
    assert len(items) == 4
    rejected_id = items[0]["id"]
    victim_id = items[1]["id"]
    manifest_keys = {b["biz_key"] for b in items}

    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": rejected_id, "reason": "冷链断链"}]},
    )
    assert r.status_code == 200

    # 外部把一张未拒收批次改成非在途 → 完成态校验必然不满足
    conn = _raw()
    conn.execute("UPDATE batches SET status = '已结清' WHERE id = ?", (victim_id,))
    conn.commit()
    conn.close()

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "失败"
    assert body["reason"]

    # 整单回滚：本趟归属变更全部撤销，清单键全部仍在交班方、无一到接班方
    sender_rows = client.get("/api/batches", params={"owner_shift_id": 2}).json()
    receiver_rows = client.get("/api/batches", params={"owner_shift_id": 3}).json()
    sender_keys = {b["biz_key"] for b in sender_rows}
    receiver_keys = {b["biz_key"] for b in receiver_rows}
    assert manifest_keys <= sender_keys
    assert not (manifest_keys & receiver_keys)

    # 拒收记录未静默消失，仍隔离可查
    rej = client.get(f"/api/handovers/{hid}/rejections").json()
    assert [row["batch_id"] for row in rej] == [rejected_id]

    reports = client.get("/api/reconcile").json()
    rep = next(r for r in reports if r["handover_id"] == hid)
    assert rep["一致"] is False
    assert rep["transferred_count"] == 0
    assert rep["rejected_count"] == 1

    # 失败也落一份分桶证明，证明归属已回滚（无一过户、清单键全在交班方）
    proof = client.get(f"/api/handovers/{hid}/proof").json()
    assert proof["一致"] is False
    assert proof["transferred_count"] == 0
    assert proof["rejected_count"] == 1
    assert proof["from_inflight_count"] == len(items) - 1  # 除被外部改状态的那张
    assert proof["to_inflight_count"] == 0
    assert set(proof["proof"]["过户键"]) == set()

    # 还原外部改动，供后续用例使用
    conn = _raw()
    conn.execute("UPDATE batches SET status = '在途' WHERE id = ?", (victim_id,))
    conn.commit()
    conn.close()


def test_reject_all_keys(client):
    started = _start(client, frm=2, to=3)
    hid = started["id"]
    items = started["items"]

    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": b["id"], "reason": "整批拒收"} for b in items]},
    )
    assert r.status_code == 200

    done = client.post(f"/api/handovers/{hid}/complete")
    body = done.json()
    assert body["status"] == "已完成"
    assert body["buckets"] == {"清单数": len(items), "过户数": 0, "拒收数": len(items)}

    # 全部留在交班方在途，接班方一张未得
    assert len(_inflight_keys(client, 3)) == 0
    assert len(_inflight_keys(client, 2)) == len(items)

    reports = client.get("/api/reconcile").json()
    rep = next(r for r in reports if r["handover_id"] == hid)
    assert rep["一致"] is True
    assert rep["transferred_count"] == 0
    assert rep["rejected_count"] == len(items)


def test_proof_persisted_and_readonly(client):
    started = _start(client, frm=2, to=3)
    hid = started["id"]
    items = started["items"]
    rejected_key = items[0]["biz_key"]
    transferred_keys = {b["biz_key"] for b in items[1:]}
    manifest_keys = {b["biz_key"] for b in items}

    # 未完成前无证明，只读接口 404
    assert client.get(f"/api/handovers/{hid}").json()["proof"] is None
    r = client.get(f"/api/handovers/{hid}/proof")
    assert r.status_code == 404

    r = client.put(
        f"/api/handovers/{hid}/rejections",
        json={"rejections": [{"batch_id": items[0]["id"], "reason": "封条破损"}]},
    )
    assert r.status_code == 200
    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.json()["status"] == "已完成"

    # 按交班单 id 只读查询持久化分桶证明
    proof = client.get(f"/api/handovers/{hid}/proof")
    assert proof.status_code == 200
    p = proof.json()
    assert p["handover_id"] == hid
    assert p["included_count"] == len(manifest_keys)
    assert p["rejected_count"] == 1
    assert p["transferred_count"] == len(transferred_keys)
    assert p["from_inflight_count"] == 1  # 拒收键留在交班方在途
    assert p["to_inflight_count"] == len(transferred_keys)
    assert set(p["proof"]["纳入键"]) == manifest_keys
    assert set(p["proof"]["拒收键"]) == {rejected_key}
    assert set(p["proof"]["过户键"]) == transferred_keys
    assert p["proof"]["覆盖清单"] is True
    assert p["proof"]["两两不交"] is True
    assert p["一致"] is True

    # 证明真实落库：绕过 API 直查 SQLite，刷新后仍在
    conn = _raw()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT included_count, rejected_count, transferred_count, proof_json "
        "FROM handover_proofs WHERE handover_id = ?",
        (hid,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert (row["included_count"], row["rejected_count"], row["transferred_count"]) == (
        len(manifest_keys), 1, len(transferred_keys)
    )

    # 交班单详情挂载同一份证明，数字与批次归属、拒收记录同源
    detail = client.get(f"/api/handovers/{hid}").json()
    assert detail["proof"]["included_count"] == detail["buckets"]["清单数"]
    assert detail["proof"]["rejected_count"] == detail["buckets"]["拒收数"]
    assert detail["proof"]["transferred_count"] == detail["buckets"]["过户数"]

    # 不存在的交班单 → 404
    assert client.get("/api/handovers/99999/proof").status_code == 404
