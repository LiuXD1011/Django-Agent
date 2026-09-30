"""Isolated browser acceptance test. Uses the existing LOCAL Langfuse login only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from playwright.sync_api import sync_playwright
    import httpx
    with tempfile.TemporaryDirectory(prefix="thinking-browser-") as temporary:
        env = {**os.environ, "DJANGO_DB_PATH": str(Path(temporary) / "app.sqlite3"),
               "DJANGO_SETTINGS_MODULE": "config.settings", "APP_TASKS_SYNC": "true",
               "LANGFUSE_AUTOSTART": "false", "LANGFUSE_ENABLED": "false"}
        os.environ.update(env)
        import django
        django.setup()
        from django.core.management import call_command
        from personal_knowledge_base.models import User, Tenant, TenantMember
        from personal_knowledge_base.authentication import issue_tokens
        from personal_knowledge_base.serializers import user_dict, tenant_dict
        with open(os.devnull, "w") as quiet:
            call_command("migrate", verbosity=0, stdout=quiet)
        tenant = Tenant.objects.create(name="Browser acceptance", api_key="browser-fixture")
        user = User.objects.create(username="browser-admin", email="browser-admin@fixture.invalid",
                                   tenant=tenant, is_system_admin=False)
        env["LANGFUSE_LOCAL_LOGIN_USER_ID"] = str(user.id)
        os.environ["LANGFUSE_LOCAL_LOGIN_USER_ID"] = str(user.id)
        TenantMember.objects.create(tenant=tenant, user=user, role="owner")
        token, refresh = issue_tokens(user)
        storage = {"personal_kb_token": token, "personal_kb_refresh_token": refresh,
                   "personal_kb_user": json.dumps(user_dict(user)),
                   "personal_kb_tenant": json.dumps(tenant_dict(tenant)),
                   "personal_kb_selected_tenant_id": str(tenant.id)}
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with open(Path(temporary) / "server.log", "w") as log:
            server = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(trust_env=False) as client:
                    for _ in range(100):
                        if server.poll() is not None:
                            raise RuntimeError("isolated server exited")
                        try:
                            if client.get(base + "/health", timeout=1).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.2)
                    else:
                        raise RuntimeError("isolated server not ready")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
                    context = browser.new_context()
                    page = context.new_page()
                    errors = []
                    requests = []
                    page.on("request", lambda request: requests.append(request.url))
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.add_init_script("const values = " + json.dumps(storage) +
                                         "; if (location.origin === " + json.dumps(base) +
                                         ") for (const [k,v] of Object.entries(values)) localStorage.setItem(k,v);")
                    session_route = "**/api/v1/observability/langfuse/session"
                    page.route(session_route, lambda route: route.fulfill(status=403, content_type="application/json",
                        body=json.dumps({"success": False, "message": "fixture: account not authorized",
                                         "error": {"code": "local_account_required"}})))
                    page.goto(base + "/platform/settings?section=langfuse")
                    page.get_by_test_id("langfuse-settings").wait_for()
                    page.get_by_role("button", name="打开 Langfuse", exact=True).click()
                    page.get_by_text("fixture: account not authorized", exact=True).wait_for()
                    assert len(context.pages) == 1, "failed login created a blank popup"
                    page.unroute(session_route)
                    with page.expect_response(lambda r: r.url.endswith("/observability/langfuse/session")) as session:
                        page.reload()
                    assert session.value.status == 200, "automatic browser login failed"
                    page.get_by_test_id("langfuse-settings").wait_for()
                    cookies = context.cookies("http://127.0.0.1:3000")
                    assert any(c["name"].startswith("next-auth.session-token") and c["httpOnly"] for c in cookies)
                    assert "next-auth.session-token" not in page.evaluate("document.cookie")
                    with page.expect_popup() as popup:
                        page.get_by_role("button", name="打开 Langfuse", exact=True).click()
                    destination = popup.value
                    destination.wait_for_url("**/project/*/traces", timeout=20000)
                    # Verify browser cookie identity through the real server, not URL alone.
                    auth = context.request.get("http://127.0.0.1:3000/api/auth/session").json()
                    assert auth.get("user", {}).get("id"), "Langfuse browser session missing"
                    destination.close()
                    page.goto(base + "/platform/settings?section=models")
                    page.get_by_role("button", name="思考级别", exact=True).first.click()
                    page.get_by_text("模型思考级别", exact=True).wait_for()
                    page.get_by_role("radio", name="开启", exact=True).check()
                    page.locator("#thinking-effort").select_option("max")
                    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/thinking")) as saved:
                        page.get_by_role("button", name="保存设置", exact=True).click()
                    assert saved.value.status == 200
                    page.get_by_text("已保存，下一轮调用生效；其他角色保持不变。", exact=True).wait_for()
                    page.get_by_role("button", name="重新加载", exact=True).click()
                    page.wait_for_timeout(300)
                    assert page.locator("#thinking-effort").input_value() == "max"
                    page.locator("#thinking-role").select_option("summary")
                    assert page.get_by_role("radio", name="默认", exact=True).is_checked()
                    artifacts = ROOT / ".cache/settings-ui-cleanup"
                    artifacts.mkdir(exist_ok=True)
                    # Mode cards, role switching, retry loading and footer stay usable.
                    page.locator("#thinking-role").select_option("chat")
                    page.wait_for_timeout(250)
                    assert page.locator(".thinking-settings-dialog").evaluate("(e) => { const r=e.getBoundingClientRect(); return r.top >= 16 && r.bottom <= innerHeight - 16; }")
                    page.screenshot(path=str(artifacts / "thinking-desktop.png"))
                    assert page.locator(".thinking-settings-dialog").evaluate("(e) => !e.closest('main')")
                    assert page.get_by_role("button", name="保存设置", exact=True).evaluate("""(e) => {
                      const r = e.getBoundingClientRect();
                      return r.top >= 0 && r.bottom <= innerHeight &&
                        e.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2));
                    }""")
                    panel = page.get_by_test_id("thinking-panel")
                    bounds = panel.bounding_box()
                    assert bounds and bounds["width"] >= 450
                    page.get_by_role("button", name="关闭", exact=True).click()
                    buttons = page.get_by_test_id("thinking-settings-button")
                    for button in buttons.all():
                        assert button.evaluate("(e) => e.parentElement.classList.contains('settings-model-actions')")
                        rect = button.bounding_box()
                        assert rect and rect["width"] >= 100 and rect["height"] <= 44
                        assert button.evaluate("(e) => getComputedStyle(e).whiteSpace") == "nowrap"
                    buttons.first.scroll_into_view_if_needed()
                    page.screenshot(path=str(artifacts / "models-desktop.png"))
                    for section in ["parser", "storage"]:
                        page.goto(base + "/platform/settings?section=" + section)
                        page.wait_for_url("**section=general")
                        assert page.get_by_role("button", name="解析引擎", exact=False).count() == 0
                        assert page.get_by_role("button", name="存储引擎", exact=False).count() == 0
                    assert not any("/parser-engines" in u or "/storage-engine" in u or
                                   "parser-engine-config" in u or "storage-engine-config" in u for u in requests)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.goto(base + "/platform/settings?section=models")
                    mobile_button = page.get_by_test_id("thinking-settings-button").first
                    mobile_button.wait_for()
                    mobile_button.scroll_into_view_if_needed()
                    box = mobile_button.bounding_box()
                    assert box and box["width"] >= 100 and box["height"] <= 44
                    assert box["x"] >= 0 and box["x"] + box["width"] <= 390
                    page.screenshot(path=str(artifacts / "models-mobile.png"))
                    mobile_button.click()
                    page.locator("#thinking-role").wait_for()
                    assert page.get_by_role("radio", name="开启", exact=True).is_checked()
                    page.get_by_role("button", name="保存设置", exact=True).scroll_into_view_if_needed()
                    assert panel.evaluate("(e) => e.scrollWidth <= e.clientWidth + 1")
                    assert page.get_by_role("button", name="保存设置", exact=True).evaluate("""(e) => {
                      const r = e.getBoundingClientRect();
                      return r.top >= 0 && r.bottom <= innerHeight &&
                        e.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2));
                    }""")
                    page.wait_for_timeout(250)
                    assert page.locator(".thinking-settings-dialog").evaluate("(e) => { const r=e.getBoundingClientRect(); return r.top >= 16 && r.bottom <= innerHeight - 16; }")
                    page.screenshot(path=str(artifacts / "thinking-mobile.png"))
                    page.get_by_role("button", name="关闭", exact=True).click()
                    # The clear API must expire the same HttpOnly cookie jar.
                    cleared = page.evaluate("""async () => {
                      const r = await fetch('/api/v1/observability/langfuse/session/clear', {
                        method: 'POST', headers: {'Authorization': 'Bearer ' + localStorage.getItem('personal_kb_token'),
                          'Content-Type': 'application/json'}, body: '{}'});
                      return r.status;
                    }""")
                    assert cleared == 200
                    assert not any(c["name"].startswith("next-auth.session-token") for c in context.cookies())
                    assert not errors, errors
                    browser.close()
                print("BROWSER_PASS: no_engine_pages_or_requests, old_links_redirect, horizontal_card_actions, responsive_dialog, bound_non_admin, explicit_error, no_failed_popup, auto_login, HttpOnly, project_open, thinking_save_reload, role_isolation, clear_session, no_page_errors")
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
