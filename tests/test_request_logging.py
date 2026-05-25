from app.middleware.request_logging import RequestLoggingMiddleware


def test_request_logging_masks_sensitive_headers():
    middleware = RequestLoggingMiddleware(app=lambda scope, receive, send: None)

    headers = middleware._sanitize_headers(  # noqa: SLF001
        {
            "authorization": "Bearer secret",
            "Cookie": "raven_user_token=secret",
            "set-cookie": "session=secret",
            "user-agent": "pytest",
        }
    )

    assert headers["authorization"] == "***"
    assert headers["Cookie"] == "***"
    assert headers["set-cookie"] == "***"
    assert headers["user-agent"] == "pytest"
