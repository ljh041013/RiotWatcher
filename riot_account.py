"""Independent Riot account's TLS XMPP presence stream (experimental).

Protocol references: valapidocs.techchrism.me/endpoint/xmpp-connection and
github.com/techchrism/valorant-xmpp-watcher. No local client auth is used here.
Tokens are held in memory only. Socket/HTTP errors must never include tokens.
"""
import base64
from collections import deque
import json
import socket
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import requests


def tag(element):
    return element.tag.rsplit('}', 1)[-1]


def child(element, name):
    return next((item for item in element if tag(item) == name), None)


def value(element, name, default=''):
    item = child(element, name)
    return (item.text or default) if item is not None else default


class XMLStream:
    """Parse arbitrarily fragmented UTF-8 XML, retaining no consumed stanzas."""
    def __init__(self):
        self.parser = ET.XMLPullParser(events=('start', 'end'))
        self.depth = 0
        self.root = None
        self.pending_bytes = 0
        self.tail = b''
        self.pending = deque()

    def feed(self, data):
        self.pending_bytes += len(data)
        if self.pending_bytes > 2_000_000 or b'<!' in self.tail + data:
            raise ValueError('Invalid XML stream')
        self.tail = data[-1:]
        self.parser.feed(data)
        result = []
        for event, element in self.parser.read_events():
            if event == 'start':
                self.depth += 1
                if self.depth == 1:
                    self.root = element
            else:
                if self.depth == 2:
                    result.append(element)
                    self.root.remove(element)
                    self.pending_bytes = 0
                self.depth -= 1
        return result


class Friends:
    def __init__(self):
        self.names = {}
        self.resources = {}

    def apply(self, stanza):
        if tag(stanza) == 'iq':
            for query in stanza:
                if tag(query) != 'query' or 'roster' not in query.tag:
                    continue
                for item in query:
                    if tag(item) != 'item':
                        continue
                    key = item.get('jid', '').split('@')[0]
                    if not key:
                        continue
                    if item.get('subscription') == 'remove':
                        self.names.pop(key, None)
                        self.resources.pop(key, None)
                        continue
                    riot_id = child(item, 'id')
                    name = riot_id.get('name', '') if riot_id is not None else ''
                    tagline = riot_id.get('tagline', '') if riot_id is not None else ''
                    self.names[key] = (name + ('#' + tagline if tagline else '')) or item.get('name') or key
            return
        if tag(stanza) != 'presence':
            return
        jid = stanza.get('from', '')
        key = jid.split('@')[0]
        if not key or key not in self.names:
            return
        resources = self.resources.setdefault(key, {})
        presence_type = stanza.get('type', '')
        if presence_type in ('unavailable', 'error'):
            if '/' in jid:
                resources.pop(jid, None)
            else:
                resources.clear()
            return
        if presence_type:
            return
        games = child(stanza, 'games')
        rows = []
        if games is not None:
            for game in games:
                product = value(game, 's.p') or tag(game)
                # Keystone is a chat transport, including dormant mobile sessions.
                if product == 'keystone':
                    continue
                state = value(game, 'st', value(stanza, 'show', 'chat'))
                if state in ('offline', 'unavailable'):
                    continue
                rows.append({'puuid': key, 'name': self.names[key], 'product': product,
                             'state': state, 'private': value(game, 'p'),
                             'summary': value(game, 'm'), 'basic': value(game, 's.a'),
                             'resource': jid.split('/', 1)[-1]})
        resources[jid] = rows

    def snapshot(self):
        rows = []
        for key, name in self.names.items():
            candidates = [row for values in self.resources.get(key, {}).values() for row in values]
            def priority(row):
                return (row['product'] in ('valorant', 'league_of_legends'),
                        row['product'] == 'ritoplus', row['state'] == 'chat')
            rows.append({**max(candidates, key=priority), 'name': name} if candidates else
                        {'puuid': key, 'name': name, 'state': 'offline', 'product': 'riot_client'})
        return rows


class DirectAccount:
    def __init__(self, credentials, callback):
        self.credentials = credentials
        self.callback = callback
        self.stop = threading.Event()
        self.socket = None
        self.label = '별도 계정'
        self.rows = None
        self.stage = '인증'
        self.thread = threading.Thread(target=self.run, daemon=True)

    def close(self):
        self.stop.set()
        connection = self.socket
        if connection:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def send(self, text):
        if self.stop.is_set():
            raise ConnectionError('Stopped')
        self.socket.sendall(text.encode('utf-8'))

    def receive(self, stream, predicate, deadline):
        while not self.stop.is_set() and time.monotonic() < deadline:
            while stream.pending:
                stanza = stream.pending.popleft()
                if tag(stanza) in ('failure', 'error') or stanza.get('type') == 'error':
                    raise ConnectionError('Server rejected connection')
                if predicate(stanza):
                    return stanza
            try:
                data = self.socket.recv(65536)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionError('Disconnected')
            stream.pending.extend(stream.feed(data))
        raise TimeoutError('Handshake timed out')

    def connect(self):
        token = self.credentials['access_token']
        with requests.Session() as session:
            session.trust_env = False
            session.headers.update({'Authorization': 'Bearer ' + token, 'User-Agent': ''})
            def get(url):
                response = session.get(url, timeout=15)
                response.raise_for_status()
                return response
            self.stage = '계정 정보'
            user = get('https://auth.riotgames.com/userinfo').json()
            account = user.get('acct', {})
            self.label = account.get('game_name', '별도 계정') + ('#' + account['tag_line'] if account.get('tag_line') else '')
            self.stage = '이용 권한 인증'
            response = session.post('https://entitlements.auth.riotgames.com/api/token/v1', json={}, timeout=15)
            response.raise_for_status()
            entitlement = response.json()['entitlements_token']
            self.stage = '채팅 인증'
            pas = get('https://riot-geo.pas.si.riotgames.com/pas/v1/service/chat').text.strip()
            payload = pas.split('.')[1]
            affinity = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))['affinity']
            session.headers['X-Riot-Entitlements-JWT'] = entitlement
            self.stage = '서버 정보'
            config = get('https://clientconfig.rpg.riotgames.com/api/v1/config/player?app=Riot%20Client').json()
        host = config['chat.affinities'][affinity]
        domain = config['chat.affinity_domains'][affinity] + '.pvp.net'
        if self.stop.is_set():
            return
        self.stage = '친구 서버 연결'
        raw = socket.create_connection((host, 5223), timeout=10)
        try:
            self.socket = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        except Exception:
            raw.close()
            raise
        self.socket.settimeout(2)
        opener = '<?xml version="1.0"?><stream:stream to=' + quoteattr(domain) + ' version="1.0" xmlns:stream="http://etherx.jabber.org/streams">'
        stream = XMLStream()
        self.send(opener)
        features = self.receive(stream, lambda e: tag(e) == 'features', time.monotonic() + 20)
        if not any(e.text == 'X-Riot-RSO-PAS' for e in features.iter()):
            raise ConnectionError('Unsupported authentication')
        self.send('<auth mechanism="X-Riot-RSO-PAS" xmlns="urn:ietf:params:xml:ns:xmpp-sasl"><rso_token>' + escape(token) + '</rso_token><pas_token>' + escape(pas) + '</pas_token></auth>')
        self.receive(stream, lambda e: tag(e) == 'success', time.monotonic() + 20)
        stream = XMLStream()
        self.send(opener)
        self.receive(stream, lambda e: tag(e) == 'features', time.monotonic() + 20)
        for identifier, body in [
            ('bind', '<bind xmlns="urn:ietf:params:xml:ns:xmpp-bind"/>'),
            ('session', '<session xmlns="urn:ietf:params:xml:ns:xmpp-session"/>'),
            ('entitlements', '<entitlements xmlns="urn:riotgames:entitlements"><token xmlns="">' + escape(entitlement) + '</token></entitlements>'),
        ]:
            self.send('<iq id="' + identifier + '" type="set">' + body + '</iq>')
            self.receive(stream, lambda e: tag(e) == 'iq' and e.get('id') == identifier and e.get('type') == 'result', time.monotonic() + 20)
        self.stage = '친구 목록 수신'
        self.send('<iq type="get" id="roster"><query xmlns="jabber:iq:riotgames:roster" last_state="true"/></iq>')
        roster = self.receive(stream, lambda e: tag(e) == 'iq' and e.get('id') == 'roster', time.monotonic() + 20)
        friends = Friends()
        friends.apply(roster)
        self.send('<presence/>')
        # Accumulate the initial burst before establishing alert baselines.
        initial_until = time.monotonic() + 2
        ready = False
        keepalive = time.monotonic()
        while not self.stop.is_set():
            stanzas = list(stream.pending)
            stream.pending.clear()
            try:
                if not stanzas:
                    data = self.socket.recv(65536)
                    if not data:
                        raise ConnectionError('Disconnected')
                    stanzas = stream.feed(data)
            except socket.timeout:
                pass
            for stanza in stanzas:
                if tag(stanza) == 'error':
                    raise ConnectionError('Stream error')
                friends.apply(stanza)
                if tag(stanza) == 'iq' and stanza.get('type') == 'set':
                    self.send('<iq type="result" id=' + quoteattr(stanza.get('id', '')) + '/>')
                if ready and tag(stanza) in ('presence', 'iq'):
                    self.rows = friends.snapshot()
                    self.callback('snapshot', self.rows)
            if not ready and time.monotonic() >= initial_until:
                ready = True
                self.rows = friends.snapshot()
                self.callback('snapshot', self.rows)
            if time.monotonic() - keepalive > 120:
                self.send(' ')
                keepalive = time.monotonic()

    def run(self):
        try:
            while not self.stop.is_set():
                if time.time() >= self.credentials['expires_at']:
                    self.callback('error', '별도 계정 인증이 만료되었습니다. 계정 → 별도 로그인에서 다시 로그인해 주세요.')
                    return
                try:
                    self.connect()
                except Exception:
                    if not self.stop.is_set():
                        self.rows = None
                        self.callback('error', f'별도 계정 연결 실패 ({self.stage}) · 5초 뒤 재시도 · 계속 실패하면 다시 로그인해 주세요.')
                finally:
                    if self.socket:
                        self.socket.close()
                        self.socket = None
                if self.stop.wait(5):
                    return
        finally:
            self.credentials.clear()
