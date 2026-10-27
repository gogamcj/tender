
from app.core.config import get_settings
from tests.conftest import TEST_PASSWORD


def test_requires_login(make_client):
    anon = make_client(login=False)
    assert anon.get("/api/health").status_code == 200
    for path in ("/api/notices", "/api/rules", "/api/analysis/runs", "/api/costs", "/api/auth/me"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/api/calc/vat", json={}).status_code == 401


def test_login_logout_and_cookie_flags(make_client):
    c = make_client("user", "kim")
    me = c.get("/api/auth/me").json()
    assert me["username"] == "kim" and me["role"] == "user"
    r = c.post("/api/auth/login", json={"username": "kim", "password": TEST_PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_bearer_token_and_wrong_password(make_client):
    c = make_client("user", "lee")
    anon = make_client(login=False)
    assert anon.post("/api/auth/login", json={"username": "lee", "password": "wrong-password1"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password1"}).status_code == 401
    token = c.cookies.get("bid_session")
    assert anon.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_lockout_after_repeated_failures(make_client):
    make_client("user", "park")
    anon = make_client(login=False)
    for _ in range(get_settings().login_max_failures):
        assert anon.post("/api/auth/login", json={"username": "park", "password": "bad-password-1"}).status_code == 401
    # 맞는 비밀번호여도 잠금 시간 동안 거부
    assert anon.post("/api/auth/login", json={"username": "park", "password": TEST_PASSWORD}).status_code == 429


def test_password_stored_as_argon2(make_client, engine):
    from sqlalchemy import text

    make_client("user", "choi")
    with engine.connect() as conn:
        h = conn.execute(text("select password_hash from users where username='choi'")).scalar()
    assert h.startswith("$argon2id$") and TEST_PASSWORD not in h
    with engine.connect() as conn:
        tokens = conn.execute(text("select token_hash from user_sessions")).scalars().all()
    assert all(len(t) == 64 for t in tokens)


def test_viewer_is_read_only_and_cannot_see_costs(make_client):
    viewer = make_client("viewer", "view")
    assert viewer.get("/api/notices").status_code == 200
    assert viewer.post("/api/notices", json={"notice_number": "V-1", "title": "x"}).status_code == 403
    assert viewer.get("/api/costs").status_code == 403


def test_admin_only_endpoints(make_client):
    user = make_client("user", "han")
    assert user.post("/api/rules", json={}).status_code == 403
    assert user.post("/api/collections", json={}).status_code == 403
    assert user.get("/api/users").status_code == 403
    admin = make_client("admin")
    assert admin.get("/api/users").status_code == 200


def test_cost_visible_only_to_owner_and_admin(make_client):
    a = make_client("user", "owner")
    b = make_client("user", "other")
    admin = make_client("admin")
    cid = a.post("/api/costs", json={"material_cost": "1000"}).json()["id"]
    assert a.get(f"/api/costs/{cid}").status_code == 200
    assert b.get(f"/api/costs/{cid}").status_code == 404
    assert b.put(f"/api/costs/{cid}", json={"material_cost": "1"}).status_code == 404
    assert b.post("/api/costs/evaluate", json={"cost_id": cid}).status_code == 404
    assert b.get("/api/costs").json() == []
    assert admin.get(f"/api/costs/{cid}").status_code == 200
    assert [r["id"] for r in a.get("/api/costs").json()] == [cid]


def test_user_management(make_client):
    admin = make_client("admin")
    r = admin.post("/api/users", json={"username": "new1", "password": "short", "role": "user"})
    assert r.status_code == 422
    r = admin.post("/api/users", json={"username": "new1", "password": "new1-password", "role": "user"})
    assert r.status_code == 422  # 사용자 이름 포함
    r = admin.post("/api/users", json={"username": "new1", "password": "Strong-pass-77", "role": "user"})
    assert r.status_code == 201
    uid = r.json()["id"]
    anon = make_client(login=False)
    assert anon.post("/api/auth/login", json={"username": "new1", "password": "Strong-pass-77"}).status_code == 200
    assert admin.patch(f"/api/users/{uid}", json={"is_active": False}).json()["is_active"] is False
    assert anon.get("/api/auth/me").status_code == 401  # 비활성화하면 세션도 끊김
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 400


def test_change_password_revokes_sessions(make_client):
    c = make_client("user", "jung")
    assert c.post("/api/auth/password", json={"current_password": "x", "new_password": "Another-pass-9"}).status_code == 400
    assert c.post("/api/auth/password", json={"current_password": TEST_PASSWORD, "new_password": "Another-pass-9"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_cli_create_user(engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app import cli

    monkeypatch.setattr(cli, "get_session_factory", lambda: sessionmaker(bind=engine))
    monkeypatch.setenv("BID_NEW_USER_PASSWORD", "Admin-pass-2026")
    assert cli.main(["create-user", "boss", "--role", "admin"]) == 0
    monkeypatch.setenv("BID_NEW_USER_PASSWORD", "weak")
    assert cli.main(["create-user", "boss2"]) == 2
