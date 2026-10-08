from actions import open_app


def test_youtube_prefers_installed_native_app(monkeypatch):
    calls = []
    monkeypatch.setattr(
        open_app,
        "_launch_native_site_app",
        lambda target: calls.append(("native", target["name"])) or True,
    )
    monkeypatch.setattr(
        open_app,
        "_open_site_in_browser",
        lambda url: calls.append(("browser", url)) or True,
    )

    result = open_app.open_app({"app_name": "YouTube"})

    assert result == "Opened YouTube app."
    assert calls == [("native", "YouTube")]


def test_chatgpt_falls_back_to_browser_when_native_app_is_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        open_app,
        "_launch_native_site_app",
        lambda target: calls.append(("native", target["name"])) or False,
    )
    monkeypatch.setattr(
        open_app,
        "_open_site_in_browser",
        lambda url: calls.append(("browser", url)) or True,
    )

    result = open_app.open_app({"app_name": "ChatGPT"})

    assert result == "Opened ChatGPT in your browser."
    assert calls == [
        ("native", "ChatGPT"),
        ("browser", "https://chatgpt.com"),
    ]


def test_site_open_reports_browser_fallback_failure(monkeypatch):
    monkeypatch.setattr(open_app, "_launch_native_site_app", lambda target: False)
    monkeypatch.setattr(open_app, "_open_site_in_browser", lambda url: False)

    result = open_app.open_app({"app_name": "YouTube.com"})

    assert "no matching native app was found" in result
    assert "browser fallback failed" in result
