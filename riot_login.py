"""Interactive Riot login in an isolated, ephemeral WebView2 process.

No password entry or cookie extraction is implemented by RiotWatcher. Only the
OAuth redirect is read; credentials are returned through a private process pipe.
"""
import secrets
import time
from urllib.parse import urlencode, urlsplit, parse_qs


REDIRECT_URL = 'https://playvalorant.com/opt_in'
REDIRECT_ORIGIN_PATH = urlsplit(REDIRECT_URL)[:3]


def login_url(state):
    return 'https://auth.riotgames.com/authorize?' + urlencode({
        'client_id': 'play-valorant-web-prod',
        'redirect_uri': REDIRECT_URL,
        'response_type': 'token id_token', 'scope': 'account openid',
        'nonce': secrets.token_urlsafe(24), 'state': state, 'prompt': 'login',
    })


def parse_redirect(url, state):
    parsed = urlsplit(url or '')
    if parsed[:3] != REDIRECT_ORIGIN_PATH:
        return None
    values = parse_qs(parsed.fragment)
    if values.get('state') != [state]:
        raise ValueError('Riot login state mismatch')
    if values.get('error'):
        raise ValueError('Riot login rejected')
    tokens = values.get('access_token', [])
    if len(tokens) != 1 or values.get('token_type', [''])[0].lower() != 'bearer':
        raise ValueError('Riot login response has no bearer token')
    token = tokens[0]
    if not token.isascii() or not token.isprintable() or ' ' in token:
        raise ValueError('Invalid bearer token')
    lifetime = int(values.get('expires_in', ['0'])[0])
    if lifetime < 60 or lifetime > 86400:
        raise ValueError('Invalid expiration')
    return {'access_token': token, 'expires_at': time.time() + lifetime - 30}


def login_process(pipe, cancel):
    # Imported only in the spawned process; Tk and WebView each own a main loop.
    import logging
    import queue
    import tempfile
    import webview
    logging.getLogger('pywebview').disabled = True
    state = secrets.token_urlsafe(32)
    results = queue.SimpleQueue()
    window = webview.create_window('RiotWatcher · 별도 계정 로그인', login_url(state),
                                   width=540, height=760, min_size=(480, 650))

    def navigation_start(_, event):
        try:
            credentials = parse_redirect(str(event.Uri), state)
        except ValueError:
            event.Cancel = True
            results.put(('error', '라이엇 로그인 응답을 확인할 수 없습니다. 별도 계정 로그인을 다시 시도해 주세요.'))
        else:
            if credentials is not None:
                # The authorized callback now redirects to a localized 404.
                # Finish the OAuth handoff before any request to that page.
                event.Cancel = True
                results.put(('ok', credentials))

    def attach_navigation_handler():
        try:
            window.native.browser.webview.NavigationStarting += navigation_start
        except AttributeError:
            results.put(('error', '로그인 창에 Microsoft Edge WebView2가 필요합니다.'))

    def watch():
        while not window.events.closed.is_set() and not cancel.is_set():
            try:
                result = results.get(timeout=0.1)
            except queue.Empty:
                continue
            if not cancel.is_set():
                try:
                    pipe.send(result)
                except (BrokenPipeError, OSError):
                    pass
            break
        if not window.events.closed.is_set():
            window.destroy()

    window.events.before_show += attach_navigation_handler
    try:
        with tempfile.TemporaryDirectory(prefix='RiotWatcher-login-') as profile:
            webview.start(watch, gui='edgechromium', private_mode=True,
                          storage_path=profile, debug=False)
    except Exception:
        try:
            pipe.send(('error', '로그인 창을 열지 못했습니다. Microsoft Edge WebView2 설치를 확인해 주세요.'))
        except (BrokenPipeError, OSError):
            pass
    finally:
        pipe.close()
