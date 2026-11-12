"""Test giai đoạn 4 — chạy KHÔNG cần mạng, không cần API key (mọi lời gọi ra ngoài đều giả lập).

    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:                                  # máy thử có thể chưa cài python-dotenv
    import dotenv  # noqa: F401
except ImportError:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from src import db, review
from src import telegram_bot as tg
from src.publish import metadata, youtube

CFG = {
    "channel": {"name": "Thế giới qua con số", "description": "kênh dữ liệu"},
    "policy_rules": "không giật tít",
    "publish": {
        "youtube": {"mode": "manual", "privacy": "public", "category_id": "27",
                    "made_for_kids": False, "contains_synthetic_media": True,
                    "notify_subscribers": True, "publish_time_local": None,
                    "utc_offset_hours": 7},
        "hashtags_fixed": ["#thegioiquaconso", "#Shorts"],
        "max_hashtags": 5,
        "disclosure": "Giọng đọc được tạo bằng AI.",
    },
}
IDEA = {"title": "파리협정 10년…해마다 54만명꼴로 폭염에 숨졌다",
        "angle": "trung bình mỗi năm có tới 54.000 người tử vong",   # số SAI có thật trong DB
        "source_name": "Hankyoreh", "source_url": "https://www.hani.co.kr/x.html"}
SCENES = [{"voice": "Đừng phớt lờ những con số này sau 10 năm Thỏa thuận Paris!"},
          {"voice": "Có trung bình 540.000 người tử vong mỗi năm."}]
OWNER = "111"


class MetadataTest(unittest.TestCase):
    def test_finalize_builds_description_with_source_disclosure_hashtags(self):
        raw = {"title": "  Vì sao 540.000 người chết\nvì nắng nóng mỗi năm? ",
               "description": "Mười năm sau Paris.\n#khihau #nangnong",
               "hashtags": ["#Khí Hậu", "nắng nóng", "#Shorts", "#x", "#dulieu", "#khoahoc"],
               "tags": ["biến đổi khí hậu", "Biến đổi khí hậu", "nắng nóng"]}
        m = metadata.finalize(raw, IDEA, SCENES, CFG)
        self.assertEqual(m["title"], "Vì sao 540.000 người chết vì nắng nóng mỗi năm?")
        self.assertEqual(m["warnings"], [])
        self.assertEqual(m["hashtags"][:2], ["#thegioiquaconso", "#Shorts"])   # cố định đứng đầu
        self.assertIn("#khihau", m["hashtags"])
        self.assertNotIn("#x", m["hashtags"])                                  # quá ngắn -> bỏ
        self.assertEqual(len(m["hashtags"]), 5)                                # 6 hợp lệ, giới hạn 5
        self.assertEqual(len(set(h.lower() for h in m["hashtags"])), 5)        # không trùng
        d = m["description"]
        self.assertTrue(d.startswith("Mười năm sau Paris."))
        self.assertNotIn("#nangnong #", d.split("\n\n")[0])                    # dòng hashtag LLM bị gỡ
        self.assertIn("Nguồn: Hankyoreh — https://www.hani.co.kr/x.html", d)
        self.assertIn("Giọng đọc được tạo bằng AI.", d)
        self.assertTrue(d.rstrip().endswith(" ".join(m["hashtags"])))
        self.assertEqual(m["tags"], ["biến đổi khí hậu", "nắng nóng"])         # bỏ trùng

    def test_title_number_not_in_script_is_flagged(self):
        # 54.000 nằm trong "góc" chưa kiểm chứng, KHÔNG nằm trong lời đọc -> phải bị bắt
        m = metadata.finalize({"title": "54.000 người chết vì nắng nóng"}, IDEA, SCENES, CFG)
        self.assertTrue(any("54000" in w for w in m["warnings"]))

    def test_limits(self):
        raw = {"title": "chữ " * 60, "description": "x " * 6000,
               "tags": [f"từ khoá số {i} rất dài" for i in range(60)]}
        m = metadata.finalize(raw, IDEA, SCENES, CFG)
        self.assertLessEqual(len(m["title"]), 100)
        self.assertLessEqual(len(m["description"]), 5000)
        self.assertIn("Nguồn:", m["description"])          # cắt tóm tắt, không cắt nguồn
        self.assertLessEqual(sum(len(t) + 3 for t in m["tags"]), 400)
        self.assertNotIn("<", metadata.finalize({"title": "a <b> c"}, IDEA, SCENES, CFG)["title"])

    def test_no_body_still_keeps_source(self):
        m = metadata.finalize({"title": "Tiêu đề"}, IDEA, SCENES, CFG)
        self.assertTrue(m["description"].startswith("Nguồn: Hankyoreh"))

    def test_build_metadata_falls_back_to_hook_after_two_bad_titles(self):
        bad = {"title": "99 lý do", "description": "d", "hashtags": [], "tags": []}
        with mock.patch("src.crew.write_metadata", return_value=bad) as wm:
            m = metadata.build_metadata(IDEA, SCENES, ["Hook đã kiểm chứng"], CFG)
        self.assertEqual(wm.call_count, 2)
        self.assertIsNotNone(wm.call_args_list[1].kwargs["feedback"])   # lần 2 có nhận xét
        self.assertEqual(m["title"], "Hook đã kiểm chứng")


class DbCase(unittest.TestCase):
    """Mỗi test dùng một file DB tạm, không đụng data/pipeline.db thật."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        p = mock.patch.object(db, "DB_PATH", self.root / "t.db")
        p.start(); self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": OWNER, "TELEGRAM_BOT_TOKEN": "T0KEN"})
        env.start(); self.addCleanup(env.stop)
        self.con = db.connect()
        self.addCleanup(self.con.close)
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,source_name)"
                         " VALUES (1,'t','t','https://s','Nguồn')")
        self.con.execute("INSERT INTO scripts (id,idea_id,hooks,body,status) VALUES (6,1,?,?, 'verified')",
                         (json.dumps(["hook"]), "- voice: Có 540.000 người.\n"))
        self.con.commit()

    def new_video(self):
        return db.upsert_video(self.con, 6, "output/final_6.mp4", "Tiêu đề", "Mô tả", ["a"],
                               [{"name": "Độ dài", "value": "61s", "ok": True}])


class DbTest(DbCase):
    def test_transition_is_atomic_and_stamps(self):
        vid = self.new_video()
        self.assertTrue(db.transition_video(self.con, vid, "pending_review", "approved"))
        self.assertFalse(db.transition_video(self.con, vid, "pending_review", "approved"))
        v = db.get_video(self.con, vid)
        self.assertEqual(v["status"], "approved")
        self.assertIsNotNone(v["decided_at"])
        self.assertEqual(v["tags"], ["a"])

    def test_resend_resets_but_published_is_refused(self):
        vid = self.new_video()
        db.transition_video(self.con, vid, "pending_review", "rejected")
        self.assertEqual(self.new_video(), vid)                     # cùng bản ghi
        self.assertEqual(db.get_video(self.con, vid)["status"], "pending_review")
        db.update_video(self.con, vid, status="published")
        with self.assertRaises(ValueError):
            self.new_video()

    def test_state_and_bad_column(self):
        self.assertEqual(db.get_state(self.con, "k", "0"), "0")
        db.set_state(self.con, "k", 5); db.set_state(self.con, "k", 7)
        self.assertEqual(db.get_state(self.con, "k"), "7")
        with self.assertRaises(ValueError):
            db.update_video(self.con, 1, **{"status=1; --": 1})


def cb(data, user=OWNER, chat=OWNER, mid=50):
    return {"update_id": 1, "callback_query": {
        "id": "cb1", "data": data, "from": {"id": int(user)},
        "message": {"message_id": mid, "chat": {"id": int(chat)}}}}


def text(msg, reply_to=None, user=OWNER):
    m = {"message_id": 99, "chat": {"id": int(user)}, "from": {"id": int(user)}, "text": msg}
    if reply_to:
        m["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": 2, "message": m}


class ReviewFlowTest(DbCase):
    def setUp(self):
        super().setUp()
        self.sent = []       # mọi thứ bot "gửi" đi được ghi lại ở đây
        for name in ("send_message", "send_video", "send_document",
                     "answer_callback", "clear_buttons"):
            p = mock.patch.object(tg, name, side_effect=self._rec(name))
            p.start(); self.addCleanup(p.stop)
        self.vid = self.new_video()
        db.update_video(self.con, self.vid, tg_message_id=50)

    def _rec(self, name):
        def f(*a, **k):
            self.sent.append((name, a, k))
            return 77
        return f

    def calls(self, name):
        return [c for c in self.sent if c[0] == name]

    def status(self):
        return db.get_video(self.con, self.vid)["status"]

    def test_approve_manual_sends_package_once(self):
        review.handle_update(self.con, cb(f"ok:{self.vid}"), CFG)
        self.assertEqual(self.status(), "approved")      # manual: chờ Du tự đăng
        self.assertEqual(len(self.calls("send_document")), 1)
        pkg = self.calls("send_message")[-1]
        self.assertIn("<code>Tiêu đề</code>", pkg[1][0])
        self.assertEqual(pkg[2]["buttons"], [[("📤 Đã đăng xong", f"done:{self.vid}")]])
        # bấm Duyệt lần hai (hoặc Telegram gửi lặp) -> không gửi gói lần nữa
        review.handle_update(self.con, cb(f"ok:{self.vid}"), CFG)
        self.assertEqual(len(self.calls("send_document")), 1)

    def test_stranger_cannot_approve(self):
        review.handle_update(self.con, cb(f"ok:{self.vid}", user="999", chat="999"), CFG)
        self.assertEqual(self.status(), "pending_review")
        self.assertEqual(self.sent, [])

    def test_reject_then_note_by_reply(self):
        review.handle_update(self.con, cb(f"no:{self.vid}"), CFG)
        self.assertEqual(self.status(), "rejected")
        self.assertEqual(self.calls("send_document"), [])
        review.handle_update(self.con, cb(f"ok:{self.vid}"), CFG)     # đã loại thì không duyệt lại được
        self.assertEqual(self.status(), "rejected")
        review.handle_update(self.con, text("giọng đọc hơi nhanh", reply_to=50), CFG)
        self.assertEqual(db.get_video(self.con, self.vid)["review_note"], "giọng đọc hơi nhanh")

    def test_done_button_and_link(self):
        review.handle_update(self.con, cb(f"done:{self.vid}"), CFG)   # chưa duyệt -> không được
        self.assertEqual(self.status(), "pending_review")
        review.handle_update(self.con, cb(f"ok:{self.vid}"), CFG)
        review.handle_update(self.con, text("xong nè https://youtube.com/shorts/abcdefghijk?x=1"), CFG)
        v = db.get_video(self.con, self.vid)
        self.assertEqual((v["status"], v["youtube_id"]), ("published", "abcdefghijk"))
        self.assertIsNotNone(v["published_at"])

    def test_link_from_stranger_ignored_and_bad_callback(self):
        review.handle_update(self.con, text("https://youtu.be/abcdefghijk", user="999"), CFG)
        self.assertIsNone(db.get_video(self.con, self.vid)["youtube_id"])
        review.handle_update(self.con, cb("ok:1; DROP TABLE videos"), CFG)
        self.assertEqual(self.status(), "pending_review")

    def test_publish_refuses_unapproved(self):
        with self.assertRaises(ValueError):
            review.publish(self.con, db.get_video(self.con, self.vid), CFG)

    # ---- gia hạn quyền YouTube ngay trên Telegram (app OAuth ở chế độ Testing: 7 ngày)
    def yt_env(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        for p in (mock.patch.object(youtube, "TOKEN_PATH", Path(d.name) / "tok.json"),
                  mock.patch.dict(os.environ, {"YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "sec"})):
            p.start(); self.addCleanup(p.stop)
        return Path(d.name) / "tok.json"

    def test_phone_renewal_flow(self):
        tok = self.yt_env()
        review.handle_update(self.con, text("/capquyen"), CFG)
        self.assertIn("accounts.google.com", self.calls("send_message")[-1][1][0])
        self.assertIn("127.0.0.1%3A8765", self.calls("send_message")[-1][1][0])
        state, verifier = db.get_state(self.con, "yt_auth_state"), db.get_state(self.con, "yt_auth_verifier")
        # địa chỉ từ một link cũ (state khác) -> từ chối, không đổi mã
        review.handle_update(self.con, text("http://127.0.0.1:8765/?state=cu&code=4/x"), CFG)
        self.assertIn("đã cũ", self.calls("send_message")[-1][1][0])
        self.assertFalse(tok.exists())
        post = mock.Mock(return_value=types.SimpleNamespace(json=lambda: {"refresh_token": "RT", "scope": "s"}))
        with mock.patch.object(youtube.requests, "post", post), \
             mock.patch.object(youtube, "whoami", return_value={"title": "Thế giới qua con số"}):
            review.handle_update(self.con, text(f"http://127.0.0.1:8765/?state={state}&code=4/abc&scope=x"), CFG)
        data = post.call_args.kwargs["data"]
        self.assertEqual((data["code"], data["code_verifier"], data["redirect_uri"]),
                         ("4/abc", verifier, youtube.PHONE_REDIRECT))
        self.assertEqual(json.loads(tok.read_text())["refresh_token"], "RT")
        self.assertIn("Đã gia hạn", self.calls("send_message")[-1][1][0])
        self.assertEqual(db.get_state(self.con, "yt_auth_state"), "")    # link đã dùng thì hết hiệu lực

    def test_token_reminder_once_a_day_before_it_dies(self):
        tok = self.yt_env()
        now = datetime(2026, 11, 19, 3, tzinfo=timezone.utc)
        yt = dict(CFG["publish"]["youtube"], mode="api", oauth_token_days=7)
        tok.write_text(json.dumps({"refresh_token": "r", "obtained_at": "2026-11-13T00:00:00+00:00"}))
        self.assertFalse(review.remind_token(self.con, yt, datetime(2026, 11, 15, tzinfo=timezone.utc)))
        self.assertTrue(review.remind_token(self.con, yt, now))          # ngày thứ 6: nhắc
        self.assertIn("/capquyen", self.calls("send_message")[-1][1][0])
        self.assertFalse(review.remind_token(self.con, yt, now))         # cùng ngày: không nhắc lại
        self.assertFalse(review.remind_token(self.con, dict(yt, oauth_token_days=None), now))  # Production

    def test_scheduled_video_still_private_after_its_time_is_reported(self):
        res = {"id": "abcdefghijk", "url": "https://youtube.com/shorts/abcdefghijk", "privacy": "private",
               "requested_privacy": "private", "publish_at": "2026-11-13T12:00:00Z"}
        cfg = json.loads(json.dumps(CFG)); cfg["publish"]["youtube"]["mode"] = "api"
        with mock.patch.object(youtube, "upload", return_value=res):
            review.handle_update(self.con, cb(f"ok:{self.vid}"), cfg)
        self.assertIn("19:00 13/11 giờ Việt Nam (21:00 giờ Hàn)", self.calls("send_message")[-1][1][0])
        before = datetime(2026, 11, 13, 12, 10, tzinfo=timezone.utc)
        after = datetime(2026, 11, 13, 13, 0, tzinfo=timezone.utc)
        with mock.patch.object(youtube, "get_status", return_value={"privacyStatus": "private"}) as st:
            self.assertEqual(review.check_scheduled(self.con, before), [])      # chưa tới lúc soát
            self.assertEqual(review.check_scheduled(self.con, after), [(self.vid, "private")])
            self.assertEqual(review.check_scheduled(self.con, after), [])       # chỉ soát một lần
        self.assertEqual(st.call_count, 1)
        self.assertIn("audit", self.calls("send_message")[-1][1][0])
        self.assertIn("YouTube Studio", self.calls("send_message")[-1][1][0])

    def api_cfg(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["publish"]["youtube"]["mode"] = "api"
        return cfg

    def test_api_upload_success_and_locked_private_warning(self):
        res = {"id": "abcdefghijk", "url": "https://youtube.com/shorts/abcdefghijk",
               "privacy": "private", "requested_privacy": "public", "publish_at": None}
        with mock.patch.object(youtube, "upload", return_value=res) as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.api_cfg())
            review.handle_update(self.con, cb(f"retry:{self.vid}"), self.api_cfg())
        self.assertEqual(up.call_count, 1)                  # retry sau khi đã đăng -> không upload lại
        v = db.get_video(self.con, self.vid)
        self.assertEqual((v["status"], v["youtube_privacy"]), ("published", "private"))
        self.assertIn("audit", self.calls("send_message")[-1][1][0])

    def test_missing_youtube_permission_falls_back_to_the_manual_package(self):
        # Chưa cấp quyền / token hết hạn: thử lại vô ích -> gửi gói để Du tự đăng, video không kẹt
        with mock.patch.object(youtube, "upload", side_effect=youtube.YouTubeAuthError("Thiếu YT_CLIENT_ID")):
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.api_cfg())
        self.assertEqual(self.status(), "approved")
        texts = [c[1][0] for c in self.calls("send_message")]
        self.assertTrue(any("Thiếu YT_CLIENT_ID" in t and "README" in t for t in texts))
        self.assertEqual(len(self.calls("send_document")), 1)                # gói file gốc
        self.assertEqual(self.calls("send_message")[-1][2]["buttons"],
                         [[("📤 Đã đăng xong", f"done:{self.vid}")]])
        review.handle_update(self.con, cb(f"done:{self.vid}"), self.api_cfg())
        self.assertEqual(self.status(), "published")

    def test_api_failure_returns_to_approved_with_retry(self):
        cfg = self.api_cfg()
        with mock.patch.object(youtube, "upload", side_effect=youtube.YouTubeUploadError("503")):
            with self.assertLogs("review", level="ERROR"):
                review.handle_update(self.con, cb(f"ok:{self.vid}"), cfg)
        self.assertEqual(self.status(), "approved")
        self.assertEqual(self.calls("send_message")[-1][2]["buttons"],
                         [[("🔁 Thử lại", f"retry:{self.vid}")]])
        ok = {"id": "abcdefghijk", "url": "u", "privacy": "public",
              "requested_privacy": "public", "publish_at": None}
        with mock.patch.object(youtube, "upload", return_value=ok):
            review.handle_update(self.con, cb(f"retry:{self.vid}"), cfg)
        self.assertEqual(self.status(), "published")

    def test_listen_once_saves_offset_and_survives_handler_error(self):
        ups = [dict(cb("ok:9999"), update_id=41), dict(cb(f"no:{self.vid}"), update_id=42)]
        with mock.patch.object(tg, "get_updates", return_value=ups), \
             mock.patch.object(review, "load_config", return_value=CFG):
            review.listen(once=True)
        con = db.connect()
        self.assertEqual(db.get_state(con, "tg_offset"), "43")
        self.assertEqual(db.get_video(con, self.vid)["status"], "rejected")
        con.close()

    def test_send_for_review_gates(self):
        out = self.root / "output"; out.mkdir()
        (out / "final_6.mp4").write_bytes(b"x")
        meta = {"title": "T", "description": "D", "tags": [], "hashtags": [], "warnings": []}
        bad = [{"name": "Âm lượng", "value": "-30 LUFS", "ok": False}]
        with mock.patch.object(review, "OUTPUT", out), mock.patch.object(review, "ROOT", self.root), \
             mock.patch.object(review, "load_config", return_value=CFG), \
             mock.patch("src.publish.metadata.build_metadata", return_value=meta), \
             mock.patch("builtins.print"):
            with mock.patch("src.qc.collect_checks", return_value=bad):
                self.assertIsNone(review.send_for_review(6))          # kiểm định trượt -> chặn
            self.assertEqual(self.calls("send_video"), [])
            self.con.execute("UPDATE scripts SET status='draft' WHERE id=6"); self.con.commit()
            self.assertIsNone(review.send_for_review(6, skip_qc=True))  # chưa kiểm chứng -> chặn
            self.con.execute("UPDATE scripts SET status='verified' WHERE id=6"); self.con.commit()
            ok = [{"name": "Âm lượng", "value": "-16 LUFS", "ok": True}]
            with mock.patch("src.qc.collect_checks", return_value=ok):
                vid = review.send_for_review(6)
        self.assertEqual(vid, self.vid)
        sv = self.calls("send_video")[0]
        self.assertEqual(sv[2]["buttons"], [[("✅ Duyệt đăng", f"ok:{vid}"), ("❌ Loại", f"no:{vid}")]])
        con = db.connect()
        self.assertEqual(db.get_video(con, vid)["tg_message_id"], 77)
        con.close()


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class YouTubeTest(unittest.TestCase):
    YT = CFG["publish"]["youtube"]

    def test_build_body(self):
        b = youtube.build_body("T", "D", ["a"], self.YT)
        self.assertEqual(b["status"], {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                                       "containsSyntheticMedia": True})
        self.assertEqual(b["snippet"]["categoryId"], "27")
        self.assertNotIn("tags", youtube.build_body("T", "D", [], self.YT)["snippet"])
        s = youtube.build_body("T", "D", [], self.YT, "2026-11-11T12:00:00Z")["status"]
        self.assertEqual((s["privacyStatus"], s["publishAt"]), ("private", "2026-11-11T12:00:00Z"))

    def test_compute_publish_at(self):
        cfg = dict(self.YT, publish_time_local="19:00")
        self.assertIsNone(youtube.compute_publish_at(self.YT))
        t = lambda h, m=0: datetime(2026, 11, 11, h, m, tzinfo=timezone.utc)
        self.assertEqual(youtube.compute_publish_at(cfg, t(2)), "2026-11-11T12:00:00Z")    # 9h VN -> 19h VN hôm nay
        self.assertEqual(youtube.compute_publish_at(cfg, t(11, 50)), "2026-11-12T12:00:00Z")  # còn <15' -> mai
        self.assertEqual(youtube.compute_publish_at(cfg, t(13)), "2026-11-12T12:00:00Z")

    def _upload(self, puts):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "v.mp4"; f.write_bytes(b"0123456789")
            post = mock.Mock(return_value=Resp(200, headers={"Location": "https://up/session"}))
            put = mock.Mock(side_effect=puts)
            with mock.patch.object(youtube, "access_token", return_value="AT"), \
                 mock.patch.object(youtube.requests, "post", post), \
                 mock.patch.object(youtube.requests, "put", put), \
                 mock.patch.object(youtube.time, "sleep"):
                return youtube.upload(f, "T", "D", ["a"], self.YT), post, put

    def test_upload_ok(self):
        done = Resp(200, {"id": "abcdefghijk", "status": {"privacyStatus": "private"}})
        res, post, put = self._upload([done])
        self.assertEqual(res["id"], "abcdefghijk")
        self.assertEqual((res["privacy"], res["requested_privacy"]), ("private", "public"))
        self.assertEqual(post.call_args.kwargs["params"]["uploadType"], "resumable")
        self.assertEqual(post.call_args.kwargs["headers"]["X-Upload-Content-Length"], "10")
        self.assertEqual(put.call_args.kwargs["headers"]["Content-Range"], "bytes 0-9/10")

    def test_upload_resumes_after_server_error(self):
        done = Resp(201, {"id": "abcdefghijk", "status": {"privacyStatus": "public"}})
        res, _, put = self._upload([Resp(503), Resp(308, headers={"Range": "bytes=0-3"}), done])
        self.assertEqual(res["privacy"], "public")
        self.assertEqual(put.call_args_list[1].kwargs["headers"]["Content-Range"], "bytes */10")
        self.assertEqual(put.call_args_list[2].kwargs["headers"]["Content-Range"], "bytes 4-9/10")

    def test_upload_rejected_raises(self):
        with self.assertRaises(youtube.YouTubeUploadError):
            self._upload([Resp(403, {"error": "quotaExceeded"})])

    def test_access_token_errors(self):
        with tempfile.TemporaryDirectory() as d:
            tok = Path(d) / "tok.json"
            env = {"YT_CLIENT_ID": "c", "YT_CLIENT_SECRET": "s"}
            with mock.patch.object(youtube, "TOKEN_PATH", tok), mock.patch.dict(os.environ, env):
                with self.assertRaisesRegex(youtube.YouTubeAuthError, "auth"):
                    youtube.access_token()                          # chưa cấp quyền
                tok.write_text(json.dumps({"refresh_token": "r"}))
                bad = Resp(400, {"error": "invalid_grant"})
                with mock.patch.object(youtube.requests, "post", return_value=bad):
                    with self.assertRaisesRegex(youtube.YouTubeAuthError, "7 ngày"):
                        youtube.access_token()
                good = Resp(200, {"access_token": "AT"})
                with mock.patch.object(youtube.requests, "post", return_value=good):
                    self.assertEqual(youtube.access_token(), "AT")


class TelegramTest(unittest.TestCase):
    ENV = {"TELEGRAM_CHAT_ID": OWNER, "TELEGRAM_BOT_TOKEN": "S3CRET"}

    def test_file_upload_encodes_buttons_as_json(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, self.ENV):
            f = Path(d) / "v.mp4"; f.write_bytes(b"x")
            post = mock.Mock(return_value=Resp(200, {"ok": True, "result": {"message_id": 5}}))
            with mock.patch.object(tg.requests, "post", post):
                mid = tg.send_video(f, "c" * 2000, buttons=[[("✅", "ok:1")]])
        self.assertEqual(mid, 5)
        data = post.call_args.kwargs["data"]
        self.assertEqual(json.loads(data["reply_markup"]),
                         {"inline_keyboard": [[{"text": "✅", "callback_data": "ok:1"}]]})
        self.assertEqual(len(data["caption"]), 1024)
        self.assertEqual(data["supports_streaming"], "true")

    def test_errors_return_none_and_never_log_token(self):
        with mock.patch.dict(os.environ, self.ENV):
            boom = mock.Mock(side_effect=ConnectionError("https://api.telegram.org/botS3CRET/x"))
            with mock.patch.object(tg.requests, "post", boom), self.assertLogs(tg.log, "ERROR") as lg:
                self.assertIsNone(tg.get_updates(0, timeout=0))
            self.assertNotIn("S3CRET", "\n".join(lg.output))
            api_err = mock.Mock(return_value=Resp(400, {"ok": False, "description": "Bad Request"}))
            with mock.patch.object(tg.requests, "post", api_err), self.assertLogs(tg.log, "ERROR"):
                self.assertIsNone(tg.send_message("hi"))

    def test_get_updates_passes_long_poll_timeout(self):
        with mock.patch.dict(os.environ, self.ENV):
            post = mock.Mock(return_value=Resp(200, {"ok": True, "result": []}))
            with mock.patch.object(tg.requests, "post", post):
                self.assertEqual(tg.get_updates(7, timeout=50), [])
        self.assertEqual(post.call_args.kwargs["json"]["timeout"], 50)
        self.assertEqual(post.call_args.kwargs["json"]["offset"], 7)
        self.assertEqual(post.call_args.kwargs["timeout"], 65)


if __name__ == "__main__":
    unittest.main()
