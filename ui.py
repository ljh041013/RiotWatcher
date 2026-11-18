"""Local desktop dashboard. Network work never runs on the Tk event thread."""
from datetime import datetime
import base64
import json
import math
import time
import sys
from pathlib import Path
import queue
import threading
import multiprocessing
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

import app
from details import map_label, friend_details
from notifications import activity_signature, play_notification
from matchmaking_trigger import MatchmakingTrigger
from keyboard_action import send_space_to_valorant
from riot_login import login_process
from riot_account import DirectAccount

_HTTP = threading.local()


BG = '#10141d'
PANEL = '#191f2b'
TEXT = '#edf2fa'
MUTED = '#96a3b8'
ACCENT = '#7ce3c0'
FONT = 'Malgun Gothic'
# Queue identifiers: https://github.com/truearken/valclient/blob/master/valclient/types.go
VALORANT_QUEUES = {
    'unrated': '일반전', 'competitive': '경쟁전', 'spikerush': '스파이크 돌격',
    'swiftplay': '신속플레이', 'deathmatch': '데스매치', 'hurm': '팀 데스매치',
    'ggteam': '에스컬레이션', 'onefa': '복제', 'premier': '프리미어',
    'custom': '사용자 설정 게임', 'snowball': '눈싸움', 'newmap': '신규 맵 모드',
    'skirmish2v2': '난투 2대2',
}
SETTINGS_PATH = (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent) / 'settings.json'
ASSETS_PATH = Path(__file__).with_name('assets')
DEFAULT_SETTINGS = {'interval': 0.05, 'auto_refresh': True, 'show_mobile': True,
                    'show_offline': True, 'sort_by': '활동순'}


def validate_settings(data):
    interval = float(str(data['interval']).strip())
    if not math.isfinite(interval) or not 0.01 <= interval <= 300:
        raise ValueError('새로고침 간격은 0.01~300초 사이로 입력해 주세요.')
    result = {**DEFAULT_SETTINGS, 'interval': interval}
    for key in ('auto_refresh', 'show_mobile', 'show_offline'):
        if not isinstance(data[key], bool):
            raise ValueError('표시 설정을 확인해 주세요.')
        result[key] = data[key]
    if data['sort_by'] not in ('활동순', '이름순'):
        raise ValueError('정렬 방식을 선택해 주세요.')
    result['sort_by'] = data['sort_by']
    return result


def load_settings(path):
    try:
        return validate_settings({**DEFAULT_SETTINGS, **json.loads(path.read_text(encoding='utf-8'))})
    except (OSError, ValueError, TypeError, KeyError):
        return DEFAULT_SETTINGS.copy()


DEMO_SCENES = [
    ('한눈에 보기', '일반전 매칭 대기, 스파이크 돌격 요원 선택, 신속플레이 게임 중을 비교하세요.'),
    ('1. 로비', '모드를 선택했지만 아직 매칭을 시작하지 않은 상태입니다.'),
    ('2. 매칭 대기', '같은 친구들이 각자의 모드로 매칭 중입니다. 아직 게임 중으로 집계되지 않습니다.'),
    ('3. 요원 선택', '매칭이 성사되어 요원을 고르는 중입니다. 점수는 아직 표시하지 않습니다.'),
    ('4. 게임 진행', '모드는 그대로 유지되며 맵, 점수, 파티 인원이 표시됩니다.'),
    ('5. 로비 복귀', '경기가 끝나 로비로 돌아왔습니다. 이전 경기의 점수와 맵은 사라집니다.'),
    ('6. 접속 종료', 'PC 친구들이 오프라인으로 바뀌고 모바일 접속은 별도로 남습니다.'),
    ('빈 목록', '연결은 정상이나 전달받은 친구가 없는 경우의 화면입니다.'),
    ('연결 끊김', '클라이언트 연결이 끊긴 경우입니다. 마지막 게임 상태를 현재 상태로 표시하지 않습니다.'),
]


def demo_snapshot(step):
    scene = step % len(DEMO_SCENES)
    if scene in (7, 8):
        return []
    rows = [
        {'puuid': 'demo-1', 'name': '달빛소환사#DEMO', 'product': 'league_of_legends',
         'state': 'offline' if scene == 6 else 'chat',
         'summary': {0: 'in game', 1: 'in lobby', 2: 'in queue', 3: 'champ select', 4: 'in game', 5: 'in lobby'}.get(scene, '')},
        {'puuid': 'demo-3', 'name': '주머니속친구#DEMO', 'product': 'ritoplus', 'state': 'away' if scene in (5, 6) else 'chat'},
        {'puuid': 'demo-4', 'name': '잠깐휴식#DEMO', 'product': 'riot_client', 'state': 'away'},
        {'puuid': 'demo-5', 'name': '다음에만나요#DEMO', 'product': 'riot_client', 'state': 'offline'},
    ]
    for index, (key, name, mode, map_name, score) in enumerate([
        ('demo-2', '민트에임#DEMO', 'unrated', '/Game/Maps/Ascent/Ascent', (7, 5)),
        ('demo-6', '돌격대장#DEMO', 'spikerush', '/Game/Maps/Duality/Duality', (2, 1)),
        ('demo-7', '빠른한판#DEMO', 'swiftplay', '/Game/Maps/Infinity/Infinity', (3, 2)),
    ]):
        stage = (2, 3, 4)[index] if scene == 0 else scene
        private = {'queueId': mode, 'sessionLoopState': {3: 'PREGAME', 4: 'INGAME'}.get(stage, 'MENUS'),
                   'partyState': 'MATCHMAKING' if stage == 2 else 'DEFAULT', 'partySize': index + 1, 'maxPartySize': 5}
        if stage in (3, 4):
            private['matchPresenceData'] = {'matchMap': map_name}
        if stage == 4:
            private.update(partyOwnerMatchScoreAllyTeam=score[0], partyOwnerMatchScoreEnemyTeam=score[1])
        private['playerPresenceData'] = {'accountLevel': 80 + index * 20, 'competitiveTier': 12 + index}
        private['partyPresenceData'] = {'isPartyOwner': index == 0, 'partyAccessibility': 'OPEN'}
        rows.append({'puuid': key, 'name': name, 'product': 'valorant',
                     'state': 'offline' if stage == 6 else 'chat',
                     'private': base64.b64encode(json.dumps(private).encode()).decode()})
    if scene == 0:
        rows.append({'puuid': 'demo-8', 'name': '정보미제공#DEMO', 'product': 'valorant', 'state': 'chat'})
    if scene == 6:
        for row in rows:
            if not app.is_mobile_presence(row):
                row['state'] = 'offline'
    return rows


def describe(presence):
    """Return display fields without treating a product name as active gameplay."""
    state = app._presence_state(presence)
    if state in ('offline', 'unavailable'):
        return ('오프라인', '—', '오프라인', '이 세션에서 마지막으로 확인한 친구', False)
    if app.is_mobile_presence(presence):
        # User verified that moving Riot Mobile to the background changes chat to mobile.
        phase = {'chat': '모바일 · 온라인', 'away': '모바일 · 자리 비움', 'mobile': '모바일 · 자리 비움', 'dnd': '모바일 · 다른 용무'}.get(state, '모바일 접속')
        detail = 'Riot Mobile 앱'
        return ('모바일', 'Riot Mobile', phase, detail, False)
    status = app.presence_to_status(presence)
    product = status.get('product')
    game = {'league_of_legends': '리그 오브 레전드', 'valorant': 'VALORANT',
            'teamfighttactics': '전략적 팀 전투', 'riot_client': 'Riot Client'}.get(product, 'Riot Client')
    phase = '클라이언트 접속'
    playing = False
    detail = []
    if product == 'league_of_legends':
        league = status.get('league') or {}
        phase_code = league.get('phase')
        phase = {'in_game': '게임 중', 'champ_select': '챔피언 선택', 'in_queue': '매칭 중',
                 'lobby': '로비', 'ready_check': '수락 대기'}.get(phase_code, '클라이언트 접속')
        playing = phase_code == 'in_game'
        if league.get('queue_id') is not None:
            detail.append('큐 ' + str(league['queue_id']))
    elif product == 'valorant':
        val = status.get('valorant') or {}
        playing = bool(status.get('in_game'))
        phase = '게임 중' if playing else ('요원 선택' if val.get('session_loop_state') == 'PREGAME' else '로비')
        if not playing and val.get('party_state') in ('MATCHMAKING', 'STARTING_MATCHMAKING'):
            phase = '매칭 중'
        queue_id = str(val.get('queue_id') or '').strip().lower()
        if queue_id:
            mode = VALORANT_QUEUES.get(queue_id, f'알 수 없는 모드 ({queue_id})')
            detail.append(('선택 모드: ' if phase == '로비' else '') + mode)
        else:
            detail.append('모드 정보 없음')
        if playing and val.get('round_score'):
            detail.append(val['round_score'])
        if val.get('match_map'):
            detail.append(map_label(val['match_map']))
        if val.get('party_size') is not None:
            detail.append(f"파티 {val['party_size']}명")
    if state == 'away' and not playing:
        phase = '자리 비움'
    return ('PC 접속', game, phase, ' · '.join(detail) or '—', playing)


def read_snapshot():
    if not hasattr(_HTTP, 'session'):
        _HTTP.session = app.requests.Session()
        _HTTP.session.trust_env = False
    port, password = app.get_lcu_connection()
    if port is None:
        raise ConnectionError('라이엇 클라이언트를 실행하고 로그인해 주세요.')
    try:
        return app.fetch_presences(port, password, session=_HTTP.session)
    except Exception:
        friends = app.fetch_friends(port, password, session=_HTTP.session)
        rows = []
        for friend in friends:
            rows.append({
                **friend,
                'puuid': friend.get('puuid') or friend.get('id') or app.get_display_name(friend),
                'name': app.get_display_name(friend),
                'state': friend.get('availability') or 'offline',
                'product': 'league_of_legends',
                'summary': '',
            })
        return rows


class Dashboard:
    def __init__(self, root, start_worker=True, settings_path=SETTINGS_PATH):
        self.root = root
        self.direct_account = None
        self.login_child = None
        self.login_pipe = None
        self.login_cancel = None
        self.account_window = None
        self.settings_path = Path(settings_path)
        self.settings = load_settings(self.settings_path)
        self.window_path = self.settings_path.with_name('window.json')
        self.pins_path = self.settings_path.with_name('pins.json')
        try:
            pins = json.loads(self.pins_path.read_text(encoding='utf-8'))
            self.pins = list(dict.fromkeys(pins)) if isinstance(pins, list) and all(isinstance(key, str) for key in pins) else []
        except (OSError, ValueError):
            self.pins = []
        self.demo_pins = []
        self.alerts_path = self.settings_path.with_name('alerts.json')
        try:
            alerts = json.loads(self.alerts_path.read_text(encoding='utf-8'))
            self.alert_friends = set(alerts) if isinstance(alerts, list) and all(isinstance(key, str) for key in alerts) else set()
        except (OSError, ValueError):
            self.alert_friends = set()
        self.demo_alert_friends = set()
        self.alert_baseline = {}
        self.space_friends = set()
        self.demo_space_friends = set()
        self.space_trigger = MatchmakingTrigger()
        self.space_busy = False
        self.space_revision = 0
        self.space_results = queue.Queue()
        self.mode_lock = threading.Lock()
        self.generation = 0
        self.demo = False
        self.demo_step = 0
        self.demo_timer = None
        self.demo_paused = True
        self.settings_window = None
        self.rows = {}
        self.filter = '전체'
        self.connected = False
        self.last_success = None
        self.receive_stats = ''
        self.detail_cache = None
        self.content_fit_pending = True
        self.fit_timer = None
        self.text_widths = {}
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.refresh = threading.Event()
        root.title('RiotWatcher · 친구 활동')
        root.iconbitmap(str(ASSETS_PATH / 'logo.ico'))
        screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
        max_width, max_height = max(400, screen_width - 40), max(300, screen_height - 90)
        self.screen_limits = (max_width, max_height)
        self.window_state = 'normal'
        width, height = min(1500, max_width), min(1000, max_height)
        try:
            saved = json.loads(self.window_path.read_text(encoding='utf-8'))
            if saved.get('layout_version') != 3:
                raise ValueError('Use the content-sized default.')
            width = max(min(960, max_width), min(int(saved['width']), max_width))
            height = max(min(540, max_height), min(int(saved['height']), max_height))
            self.window_state = 'zoomed' if saved.get('maximized', False) else 'normal'
        except (OSError, ValueError, TypeError, KeyError):
            pass
        self.normal_size = (width, height)
        root.geometry(f'{width}x{height}+{max(0, (screen_width-width)//2)}+{max(0, (screen_height-height-40)//2)}')
        root.minsize(min(960, max_width), min(540, max_height))
        if root.state() != 'withdrawn':
            root.state(self.window_state)
        root.bind('<Configure>', self.remember_window_size, add='+')
        root.configure(bg=BG)
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        for direction in ('Vertical', 'Horizontal'):
            scrollbar_style = f'Slim.{direction}.TScrollbar'
            self.style.layout(scrollbar_style, [
                (f'{direction}.Scrollbar.trough', {'sticky': 'nswe', 'children': [
                    (f'{direction}.Scrollbar.thumb', {'sticky': 'nswe', 'expand': '1'})
                ]})
            ])
            self.style.configure(scrollbar_style, width=8, arrowsize=8,
                                 background='#394354', troughcolor=PANEL,
                                 bordercolor=PANEL, lightcolor='#394354',
                                 darkcolor='#394354', borderwidth=0, gripcount=0)
            self.style.map(scrollbar_style,
                           background=[('pressed', '#728199'), ('active', '#56667e')],
                           lightcolor=[('pressed', '#728199'), ('active', '#56667e')],
                           darkcolor=[('pressed', '#728199'), ('active', '#56667e')])
        self.table_font = tkfont.Font(root=root, family=FONT, size=10)
        self.row_height = max(40, self.table_font.metrics('linespace') + 18)
        self.style.configure('Friends.Treeview', background=PANEL, foreground=TEXT,
                             fieldbackground=PANEL, borderwidth=0, rowheight=self.row_height, font=(FONT, 10))
        self.style.configure('Friends.Treeview.Heading', background='#222b3a', foreground=MUTED,
                             font=(FONT, 9, 'bold'), borderwidth=0, padding=(12, 12))
        self.style.map('Friends.Treeview', background=[], foreground=[])
        self.style.layout('Friends.Treeview.Item', [
            ('Treeitem.padding', {'sticky': 'nswe', 'children': [
                ('Treeitem.image', {'side': 'left', 'sticky': 'ns'})
            ]})
        ])
        self.selection_strip = tk.PhotoImage(master=root, width=8, height=self.row_height - 12)
        self.selection_strip.put(ACCENT, to=(1, 0, 4, self.row_height - 12))
        self.marked_row = None
        self.style.map('Friends.Treeview.Heading', background=[('active', '#222b3a')])
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill='both', expand=True, padx=24, pady=18)
        # Reserve the bottom area before any expanding content is packed.
        # Otherwise the table can consume the space needed by wrapped status text.
        self.status_bar = tk.Frame(outer, bg=BG)
        self.status_bar.pack(side='bottom', fill='x', pady=(12, 0))
        self.connection_label = self.label(self.status_bar, '●  연결 확인 중', 10, MUTED)
        self.connection_label.pack(anchor='w', fill='x', pady=(0, 6))
        self.footer = self.label(self.status_bar, '', 9, MUTED)
        self.footer.pack(anchor='w', fill='x')
        self.alert_status = self.label(self.status_bar, '', 9, '#b5adff')
        self.alert_status.pack(anchor='w', fill='x')
        header = tk.Frame(outer, bg=BG)
        self.header = header
        header.pack(fill='x')
        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill='x', pady=(7, 0))
        self.logo_image = tk.PhotoImage(master=root, file=str(ASSETS_PATH / 'logo-header.png'))
        tk.Label(title_row, image=self.logo_image, bg=BG).pack(side='left', padx=(0, 10))
        self.label(title_row, '친구 목록', 25, bold=True).pack(side='left')
        self.refresh_button = self.button(title_row, '새로고침 ↻', self.request_refresh)
        self.refresh_button.pack(side='right')
        self.button(title_row, '설정', self.open_settings).pack(side='right', padx=8)
        self.button(title_row, '계정', self.open_account).pack(side='right', padx=(8, 0))
        self.demo_button = self.button(title_row, '데모 보기', self.toggle_demo)
        self.demo_button.pack(side='right')
        self.account_label = self.label(header, '라이엇 클라이언트 계정 사용', 10, MUTED)
        self.account_label.pack(anchor='w', pady=(4, 12))
        metrics = tk.Frame(outer, bg=BG)
        self.metrics_frame = metrics
        metrics.pack(fill='x')
        self.metrics = {}
        for i, (name, caption, color) in enumerate([
            ('PC 접속', '데스크톱에서 접속 중', ACCENT),
            ('게임 중', '플레이 상태가 확인된 친구', '#b5adff'),
            ('모바일', '게임 플레이와 별도 표시', '#7d8796'),
        ]):
            metrics.columnconfigure(i, weight=1, uniform='cards')
            card = tk.Frame(metrics, bg=PANEL, padx=16, pady=10)
            card.grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else 7, 0 if i == 2 else 7))
            self.label(card, name, 10, MUTED).pack(anchor='w')
            value = self.label(card, '—', 24, color, bold=True)
            value.pack(anchor='w', pady=3)
            self.label(card, caption, 9, MUTED).pack(anchor='w')
            self.metrics[name] = value
        controls = tk.Frame(outer, bg=BG)
        self.controls = controls
        self.demo_panel = tk.Frame(outer, bg='#242135', padx=14, pady=10)
        demo_tools = tk.Frame(self.demo_panel, bg='#242135')
        demo_tools.pack(fill='x')
        self.label(demo_tools, 'DEMO · 가상 친구', 10, '#d5b5ff', bold=True).pack(side='left', padx=(0, 15))
        self.demo_scene = tk.StringVar(value=DEMO_SCENES[0][0])
        self.scene_picker = ttk.Combobox(demo_tools, textvariable=self.demo_scene,
                                         values=[name for name, _ in DEMO_SCENES], state='readonly', width=17)
        self.scene_picker.pack(side='left')
        self.scene_picker.bind('<<ComboboxSelected>>', lambda _: self.select_demo_scene(self.scene_picker.current()))
        self.button(demo_tools, '다음 →', lambda: self.select_demo_scene(self.demo_step + 1)).pack(side='right')
        self.demo_play_button = self.button(demo_tools, '자동 재생', self.toggle_demo_play)
        self.demo_play_button.pack(side='right', padx=6)
        self.button(demo_tools, '← 이전', lambda: self.select_demo_scene(self.demo_step - 1)).pack(side='right')
        self.demo_description = self.label(self.demo_panel, '', 10, '#c6bedf')
        self.demo_description.configure(wraplength=780, justify='left')
        self.demo_description.pack(anchor='w', pady=(8, 0))
        controls.pack(fill='x', pady=(14, 10))
        self.tabs = {}
        for name in ('전체', 'PC 접속', '모바일', '오프라인'):
            btn = self.button(controls, name, lambda n=name: self.set_filter(n))
            btn.pack(side='left', padx=(0, 6))
            self.tabs[name] = btn
        search_frame = tk.Frame(controls, bg=PANEL, padx=12, pady=8)
        search_frame.pack(side='right')
        self.label(search_frame, '검색', 9, MUTED).pack(side='left', padx=(0, 10))
        self.search = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search, bg=PANEL, fg=TEXT,
                                insertbackground=ACCENT, relief='flat', font=(FONT, 10), width=21)
        search_entry.pack(side='left')
        self.search.trace_add('write', lambda *_: self.render())
        panes = tk.PanedWindow(outer, orient='horizontal', bg=BG, sashwidth=8, bd=0)
        self.panes = panes
        panes.pack(fill='both', expand=True)
        table_frame = tk.Frame(panes, bg=PANEL)
        panes.add(table_frame, minsize=490, stretch='always')
        detail_frame = tk.Frame(panes, bg=PANEL, padx=10, pady=12, width=360)
        self.detail_frame = detail_frame
        panes.add(detail_frame, minsize=260, width=360, stretch='never')
        detail_header = tk.Frame(detail_frame, bg=PANEL)
        detail_header.pack(fill='x', pady=(0, 10))
        self.label(detail_header, '친구 상세', 13, bold=True).pack(side='left')
        self.pin_button = self.button(detail_header, '상단 고정', self.toggle_pin)
        self.pin_button.configure(state='disabled')
        self.pin_button.pack(side='right')
        self.pin_error = self.label(detail_frame, '', 9, '#f6a69c')
        self.alert_enabled = tk.BooleanVar(value=False)
        self.alert_check = tk.Checkbutton(detail_frame, text='이 친구 상태 변경 시 소리 알림',
                                         variable=self.alert_enabled, command=self.toggle_friend_alert,
                                         bg=PANEL, fg=TEXT, selectcolor=BG,
                                         activebackground=PANEL, activeforeground=ACCENT,
                                         font=(FONT, 10), anchor='w', state='disabled')
        self.alert_check.pack(fill='x', pady=(0, 4))
        sound_row = tk.Frame(detail_frame, bg=PANEL)
        sound_row.pack(fill='x', pady=(0, 8))
        self.label(sound_row, '점수 변경은 제외', 9, MUTED).pack(side='left')
        self.button(sound_row, '소리 테스트', self.test_alert_sound).pack(side='right')
        self.space_enabled = tk.BooleanVar(value=False)
        self.space_check = tk.Checkbutton(detail_frame, text='매칭 시작 시 발로란트에 Space 입력',
                                         variable=self.space_enabled, command=self.toggle_friend_space,
                                         bg=PANEL, fg=TEXT, selectcolor=BG,
                                         activebackground=PANEL, activeforeground=ACCENT,
                                         font=(FONT, 10), anchor='w', state='disabled')
        self.space_check.pack(fill='x', pady=(0, 3))
        self.label(detail_frame, '발로란트를 앞으로 가져옴 · 이번 실행에만 적용', 9, MUTED).pack(anchor='w', pady=(0, 8))
        notebook = ttk.Notebook(detail_frame)
        notebook.pack(fill='both', expand=True)
        self.detail_texts = []
        for title in ('요약', '전체 데이터'):
            page = tk.Frame(notebook, bg=PANEL)
            notebook.add(page, text=title)
            scrollbar = ttk.Scrollbar(page, orient='vertical', style='Slim.Vertical.TScrollbar')
            scrollbar.pack(side='right', fill='y')
            text = tk.Text(page, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat',
                           font=(FONT, 10), wrap='word', width=30, padx=10, pady=12,
                           yscrollcommand=scrollbar.set, state='disabled')
            text.pack(fill='both', expand=True)
            scrollbar.configure(command=text.yview)
            self.detail_texts.append(text)
        columns = ('name', 'game', 'phase', 'detail')
        self.table = ttk.Treeview(table_frame, columns=columns, show='tree headings', style='Friends.Treeview', selectmode='browse')
        self.table.heading('#0', text='')
        self.table.column('#0', width=12, minwidth=12, stretch=False)
        samples = ('가나다라마바사아자차#KR1', '리그 오브 레전드', '챔피언 선택', '스파이크 돌격 · 12-10 · 어비스 · 파티 5명')
        self.column_minimums = {col: self.table_font.measure(sample) + 36 for col, sample in zip(columns, samples)}
        for col, name in zip(columns, ('친구', '게임 / 접속 환경', '현재 상태', '상세 정보')):
            self.table.heading(col, text=name, anchor='w')
            self.table.column(col, width=self.column_minimums[col], minwidth=self.column_minimums[col], anchor='w')
        self.table.tag_configure('모바일', foreground='#7d8796')
        self.table.tag_configure('mobile_online', foreground='#91bfff')
        self.table.tag_configure('오프라인', foreground='#768398')
        self.table.tag_configure('playing', foreground=ACCENT)
        self.table.tag_configure('matchmaking', foreground='#ffbf70', background='#30271f')
        self.table.tag_configure('selection', foreground='#cfb0ff', background='#292338')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview, style='Slim.Vertical.TScrollbar')
        self.table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=self.table.xview, style='Slim.Horizontal.TScrollbar')
        self.table.configure(xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom', fill='x')
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _: self.render_details())
        self.empty = self.label(table_frame, '클라이언트에 연결하는 중입니다…', 11, MUTED)
        self.empty.place(relx=.5, rely=.5, anchor='center')
        self.connection_label.configure(justify='left')
        self.footer.configure(justify='left')
        outer.bind('<Configure>', lambda event: self.wrap_status(event.width), add='+')
        self.set_filter('전체')
        root.update_idletasks()
        self.fit_window()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = root.after(8, self.drain)
        if start_worker:
            threading.Thread(target=self.poll, daemon=True).start()

    def label(self, parent, text, size, color=TEXT, bold=False):
        return tk.Label(parent, text=text, font=(FONT, size, 'bold' if bold else 'normal'),
                        fg=color, bg=parent.cget('bg'), anchor='w')

    def wrap_status(self, width):
        self.connection_label.configure(wraplength=max(300, width - 12))
        self.footer.configure(wraplength=max(300, width - 12))
        self.alert_status.configure(wraplength=max(300, width - 12))
        self.demo_description.configure(wraplength=max(300, width - 40))

    def fit_window(self):
        # Size from rendered fonts, all four columns, the detail pane and eight rows.
        max_width, max_height = self.screen_limits
        detail_width = max(360, self.table_font.measure('대기열 진입 시각 (원본)  2026-10-07') + 55)
        self.panes.paneconfigure(self.detail_frame, width=detail_width)
        table_width = sum(self.table.column(col, 'minwidth') for col in self.table['columns']) + 36
        required_width = table_width + detail_width + 64
        chrome_height = (self.header.winfo_reqheight() + self.metrics_frame.winfo_reqheight()
                         + self.controls.winfo_reqheight() + 24 + 36
                         + max(self.status_bar.winfo_reqheight(), self.table_font.metrics('linespace') * 3) + 12)
        demo_height = self.demo_panel.winfo_reqheight() + 18 if self.demo else 0
        required_height = chrome_height + demo_height + self.row_height * 8 + 60
        width = min(max_width, max(self.normal_size[0], required_width))
        height = min(max_height, max(self.normal_size[1], required_height))
        self.normal_size = (width, height)
        self.root.geometry(f'{width}x{height}+{max(0, (self.root.winfo_screenwidth()-width)//2)}+{max(0, (self.root.winfo_screenheight()-height-40)//2)}')
        self.root.minsize(min(required_width, max_width), min(required_height, max_height))

    def finish_content_fit(self):
        self.fit_timer = None
        self.fit_window()

    def fit_columns(self, display):
        widths = self.column_minimums.copy()
        for _, _, _, values, _, _ in display:
            for col, text in zip(self.table['columns'], values):
                text = str(text)
                if text not in self.text_widths:
                    self.text_widths[text] = self.table_font.measure(text) + 36
                widths[col] = max(widths[col], self.text_widths[text])
        for col, width in widths.items():
            self.table.column(col, minwidth=width, width=max(width, self.table.column(col, 'width')))
        if len(self.text_widths) > 4000:
            self.text_widths.clear()

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=PANEL, fg=TEXT,
                         activebackground='#304039', activeforeground=ACCENT,
                         relief='flat', bd=0, padx=15, pady=9, cursor='hand2', font=(FONT, 10))

    def set_filter(self, name):
        self.filter = name
        for key, btn in self.tabs.items():
            btn.configure(bg='#29473f' if key == name else PANEL, fg=ACCENT if key == name else MUTED)
        self.render()

    def toggle_pin(self):
        selected = self.table.selection()
        if not selected or not self.connected:
            return
        key = selected[0]
        old_pins = self.demo_pins if self.demo else self.pins
        updated = [item for item in old_pins if item != key]
        if key not in old_pins:
            updated.insert(0, key)
        if self.demo:
            self.demo_pins = updated
        else:
            try:
                temporary = self.pins_path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(self.pins_path)
            except OSError:
                self.pin_error.configure(text='고정 목록을 저장하지 못했습니다.')
                self.pin_error.pack(fill='x', before=self.detail_texts[0].master.master)
                return
            self.pins = updated
        self.pin_error.pack_forget()
        self.render()
        if self.table.exists(key):
            self.table.see(key)

    def toggle_friend_alert(self):
        selected = self.table.selection()
        if not selected or not self.connected:
            return
        key = selected[0]
        enabled = self.alert_enabled.get()
        current = self.demo_alert_friends if self.demo else self.alert_friends
        updated = current | {key} if enabled else current - {key}
        if self.demo:
            self.demo_alert_friends = updated
        else:
            try:
                temporary = self.alerts_path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(sorted(updated), indent=2), encoding='utf-8')
                temporary.replace(self.alerts_path)
            except OSError:
                self.alert_enabled.set(key in current)
                self.alert_status.configure(text='알림 설정을 저장하지 못했습니다.')
                return
            self.alert_friends = updated
        if enabled:
            row = self.rows[key]
            self.alert_baseline[key] = (activity_signature(row), app.get_display_name_from_presence(row))
        else:
            self.alert_baseline.pop(key, None)
        self.render()

    def test_alert_sound(self):
        try:
            play_notification()
        except RuntimeError:
            self.alert_status.configure(text='알림음을 재생하지 못했습니다. 출력 장치를 확인해 주세요.')

    def toggle_friend_space(self):
        selected = self.table.selection()
        if not selected or not self.connected:
            return
        key = selected[0]
        self.space_revision += 1
        watched = self.demo_space_friends if self.demo else self.space_friends
        if self.space_enabled.get():
            watched.add(key)
            self.space_trigger.prime(key, self.rows[key])
        else:
            watched.discard(key)
            self.space_trigger.previous.pop(key, None)

    def check_matchmaking_action(self, rows):
        watched = self.demo_space_friends if self.demo else self.space_friends
        changed = self.space_trigger.update(rows, watched)
        if not changed:
            return
        names = ', '.join(changed)
        if self.demo:
            self.alert_status.configure(text=f'[데모] {names} 매칭 시작 → Space 입력 시뮬레이션 (실제 입력 없음)')
            return
        if self.space_busy:
            return
        self.space_busy = True
        generation = self.generation
        revision = self.space_revision
        self.alert_status.configure(text=f'{names} 매칭 시작 · 발로란트 창 확인 중…')
        def perform():
            try:
                result = send_space_to_valorant(lambda: generation == self.generation
                                                and revision == self.space_revision
                                                and not self.demo and not self.stop.is_set())
            except Exception:
                result = (False, 'Space 자동 입력 중 오류가 발생했습니다.')
            self.space_results.put((generation, result))
        # Keep the short action alive through window closing so key-up can finish.
        threading.Thread(target=perform, daemon=False).start()

    def check_status_alerts(self, rows):
        watched = self.demo_alert_friends if self.demo else self.alert_friends
        incoming = {str(row.get('puuid') or row.get('name') or ''): row for row in rows}
        updated = {}
        changes = []
        for key in watched:
            old = self.alert_baseline.get(key)
            row = incoming.get(key)
            if row is None and old is None:
                continue
            signature = activity_signature(row) if row is not None else ('offline',)
            name = app.get_display_name_from_presence(row) if row is not None else old[1]
            updated[key] = (signature, name)
            if old is not None and old[0] != signature:
                description = describe(row) if row is not None else None
                state_text = description[2] if description else '오프라인'
                if description and (row.get('product') == 'valorant'):
                    state_text += ' · ' + description[3].split(' · ')[0]
                changes.append(f'{name}: {state_text}')
        self.alert_baseline = updated
        if changes:
            prefix = '[데모] ' if self.demo else ''
            self.alert_status.configure(text=prefix + datetime.now().strftime('%H:%M:%S') + '  ' + ' / '.join(changes))
            self.test_alert_sound()

    def request_refresh(self):
        if self.demo:
            self.select_demo_scene(self.demo_step + 1)
            return
        self.refresh_button.configure(text='확인 중…', state='disabled')
        self.refresh.set()

    def toggle_demo(self):
        with self.mode_lock:
            self.demo = not self.demo
            self.generation += 1
        self.alert_baseline = {}
        self.space_trigger.reset()
        self.alert_status.configure(text='')
        self.refresh_button.configure(text='새로고침 ↻', state='normal')
        if self.demo:
            self.live_state = (self.rows, self.last_success, self.filter, self.search.get())
            self.rows = {}
            self.demo_paused = True
            self.demo_step = 0
            self.search.set('')
            self.set_filter('전체')
            self.demo_button.configure(text='데모 종료', bg='#443855', fg='#d5b5ff')
            self.refresh_button.configure(text='다음 장면 →')
            self.demo_panel.pack(fill='x', pady=(18, 0), before=self.controls)
            self.show_demo_scene()
            self.root.update_idletasks()
            self.fit_window()
        else:
            if self.demo_timer is not None:
                self.root.after_cancel(self.demo_timer)
                self.demo_timer = None
            self.rows, self.last_success, old_filter, old_search = self.live_state
            self.connected = False
            self.search.set(old_search)
            self.set_filter(old_filter)
            self.demo_button.configure(text='데모 보기', bg=PANEL, fg=TEXT)
            self.demo_panel.pack_forget()
            self.connection_label.configure(text='●  실제 클라이언트에 다시 연결하는 중…', fg=MUTED)
        self.refresh.set()

    def advance_demo(self):
        self.demo_step = (self.demo_step + 1) % len(DEMO_SCENES)
        self.show_demo_scene()

    def select_demo_scene(self, index):
        self.demo_paused = True
        self.demo_step = index % len(DEMO_SCENES)
        self.show_demo_scene()

    def toggle_demo_play(self):
        self.demo_paused = not self.demo_paused
        self.show_demo_scene()

    def show_demo_scene(self):
        if self.demo_timer is not None:
            self.root.after_cancel(self.demo_timer)
            self.demo_timer = None
        if not self.demo:
            return
        self.rows = {}
        self.demo_scene.set(DEMO_SCENES[self.demo_step][0])
        self.demo_description.configure(text=DEMO_SCENES[self.demo_step][1])
        self.demo_play_button.configure(text='일시정지' if not self.demo_paused else '자동 재생')
        if self.demo_step == 8:
            self.alert_baseline = {}
            self.space_trigger.reset()
        self.accept_snapshot(demo_snapshot(self.demo_step), check_alerts=self.demo_step != 8)
        if self.demo_step == 8:
            self.connected = False
            self.connection_label.configure(text='●  데모 모드 · 연결 끊김 시뮬레이션', fg='#edbc84')
        self.render()
        if not self.demo_paused:
            self.demo_timer = self.root.after(max(1000, round(self.settings['interval'] * 1000)), self.advance_demo)

    def apply_settings(self, data):
        settings = validate_settings(data)
        temporary = self.settings_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.settings_path)
        with self.mode_lock:
            self.settings = settings
        if self.demo_timer is not None:
            self.root.after_cancel(self.demo_timer)
            self.demo_timer = None
        if self.demo and not self.demo_paused:
            self.demo_timer = self.root.after(max(1000, round(settings['interval'] * 1000)), self.advance_demo)
        self.refresh.set()
        self.render()

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = self.settings_window = tk.Toplevel(self.root)
        win.title('RiotWatcher · 설정')
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        body = tk.Frame(win, bg=BG, padx=26, pady=24)
        body.pack(fill='both', expand=True)
        self.label(body, '설정', 19, bold=True).pack(anchor='w')
        self.label(body, '저장하면 바로 적용되며, 다음 실행에도 유지됩니다.', 10, MUTED).pack(anchor='w', pady=(6, 22))
        variables = {key: (tk.BooleanVar(value=value) if isinstance(value, bool) else tk.StringVar(value=str(value)))
                     for key, value in self.settings.items()}
        interval_row = tk.Frame(body, bg=BG)
        interval_row.pack(fill='x', pady=(0, 14))
        self.label(interval_row, '새로고침 간격', 11).pack(side='left')
        self.label(interval_row, '초 (0.01~300)', 10, MUTED).pack(side='right', padx=(8, 0))
        tk.Spinbox(interval_row, from_=0.01, to=300, increment=0.01, format='%.2f', textvariable=variables['interval'], width=7,
                   bg=PANEL, fg=TEXT, insertbackground=ACCENT, buttonbackground=PANEL,
                   font=(FONT, 11), relief='flat').pack(side='right')
        self.label(body, '0.05초: 약 20회/초 · 응답보다 짧게 설정하면 응답 속도가 한계입니다.', 9, MUTED).pack(anchor='w', pady=(0, 10))
        for key, text in [('auto_refresh', '자동 새로고침 켜기'), ('show_mobile', '전체 목록에 모바일 친구 표시'),
                          ('show_offline', '전체 목록에 오프라인 친구 표시')]:
            tk.Checkbutton(body, text=text, variable=variables[key], bg=BG, fg=TEXT,
                           activebackground=BG, activeforeground=ACCENT, selectcolor=PANEL,
                           font=(FONT, 10), anchor='w').pack(fill='x', pady=5)
        self.label(body, '숨긴 상태도 개별 탭에서 확인할 수 있습니다.', 9, MUTED).pack(anchor='w', pady=(2, 16))
        sort_row = tk.Frame(body, bg=BG)
        sort_row.pack(fill='x')
        self.label(sort_row, '친구 정렬', 11).pack(side='left')
        ttk.Combobox(sort_row, textvariable=variables['sort_by'], values=('활동순', '이름순'),
                     state='readonly', width=14, font=(FONT, 10)).pack(side='right')
        error = self.label(body, '', 9, '#f6a69c')
        error.configure(wraplength=400)
        error.pack(fill='x', pady=12)
        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill='x')
        def defaults():
            for key, value in DEFAULT_SETTINGS.items():
                variables[key].set(value)
            error.configure(text='기본값을 선택했습니다. 저장하면 적용됩니다.', fg=MUTED)
        def save():
            try:
                self.apply_settings({key: var.get() for key, var in variables.items()})
            except (ValueError, tk.TclError):
                error.configure(text='새로고침 간격은 0.01~300초 사이로 입력해 주세요.', fg='#f6a69c')
                return
            except OSError:
                error.configure(text='설정을 저장하지 못했습니다. 폴더 쓰기 권한을 확인해 주세요.', fg='#f6a69c')
                return
            win.destroy()
        self.button(buttons, '기본값', defaults).pack(side='left')
        self.button(buttons, '저장', save).pack(side='right', padx=(8, 0))
        self.button(buttons, '취소', win.destroy).pack(side='right')
        win.bind('<Escape>', lambda _: win.destroy())
        win.bind('<Return>', lambda _: save())

    def open_account(self):
        if self.account_window is not None and self.account_window.winfo_exists():
            self.account_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.account_window = win
        win.title('사용할 계정')
        win.configure(bg=BG)
        win.transient(self.root)
        body = tk.Frame(win, bg=BG, padx=24, pady=20)
        body.pack(fill='both', expand=True)
        self.label(body, '워쳐 계정', 16, bold=True).pack(anchor='w', pady=(0, 12))
        self.label(body, '클라이언트와 다른 계정의 친구 목록을 볼 수 있습니다.', 10, MUTED).pack(anchor='w')
        self.label(body, '별도 로그인은 실험 기능입니다. 라이엇 로그인 창에서 입력하세요.\n로그인은 저장하지 않으며, 재실행·인증 만료 시 다시 로그인해야 합니다.', 10, MUTED).pack(anchor='w', pady=12)
        self.button(body, '별도 계정 로그인', lambda: (win.destroy(), self.start_account_login())).pack(fill='x', pady=4)
        self.button(body, '라이엇 클라이언트 계정 사용', lambda: (win.destroy(), self.switch_account(None))).pack(fill='x', pady=4)

    def start_account_login(self):
        if self.login_child is not None and self.login_child.is_alive():
            return
        context = multiprocessing.get_context('spawn')
        self.login_pipe, sender = context.Pipe(duplex=False)
        self.login_cancel = context.Event()
        self.login_child = context.Process(target=login_process, args=(sender, self.login_cancel), daemon=True)
        self.login_child.start()
        sender.close()
        self.account_label.configure(text='별도 계정 로그인 중 · 열린 라이엇 로그인 창에서 진행해 주세요.')

    def switch_account(self, credentials):
        if credentials is None and self.login_cancel is not None:
            self.login_cancel.set()
        if self.demo:
            self.toggle_demo()
        previous = self.direct_account
        with self.mode_lock:
            self.generation += 1
            self.direct_account = None
            if credentials is not None:
                def receive(event, payload):
                    with self.mode_lock:
                        if self.direct_account is not account or self.demo or self.stop.is_set():
                            return
                        self.events.put((self.generation, event, payload))
                account = DirectAccount(credentials, receive)
                self.direct_account = account
        if previous is not None:
            previous.close()
        self.rows = {}
        self.connected = False
        self.alert_baseline = {}
        self.space_trigger.reset()
        self.space_friends.clear()
        self.space_revision += 1
        self.receive_stats = ''
        self.detail_cache = None
        self.account_label.configure(text='별도 계정 연결 중…' if credentials else '라이엇 클라이언트 계정 사용')
        self.connection_label.configure(text='●  연결 중…', fg=MUTED)
        self.render()
        if credentials is not None:
            account.thread.start()
        self.refresh.set()

    def check_account_login(self):
        if self.login_pipe is None:
            return
        try:
            if self.login_pipe.poll():
                result, payload = self.login_pipe.recv()
                if result == 'ok':
                    self.switch_account(payload)
                else:
                    self.account_label.configure(text=payload)
                self.login_pipe.close()
                self.login_pipe = None
            elif self.login_child is not None and not self.login_child.is_alive():
                self.login_pipe.close()
                self.login_pipe = None
                self.account_label.configure(text='로그인 취소됨 · 기존 계정 연결 유지')
        except (EOFError, OSError):
            self.login_pipe.close()
            self.login_pipe = None
            self.account_label.configure(text='로그인 창이 닫혔습니다. 기존 계정 연결 유지')

    def poll(self):
        previous_received = None
        previous_generation = None
        while not self.stop.is_set():
            self.refresh.clear()
            started = time.monotonic()
            failed = False
            with self.mode_lock:
                generation, demo, direct = self.generation, self.demo, self.direct_account
            if not demo and direct is not None:
                if direct.rows is not None:
                    self.events.put((generation, 'snapshot', direct.rows))
                self.refresh.wait()
                continue
            if not demo:
                try:
                    rows = read_snapshot()
                    received = time.monotonic()
                    cadence = received - previous_received if previous_received is not None and generation == previous_generation else None
                    previous_received, previous_generation = received, generation
                    self.events.put((generation, 'timed_snapshot', (rows, received - started, received, cadence)))
                except Exception:
                    failed = True
                    previous_received = None
                    self.events.put((generation, 'error', None))
            with self.mode_lock:
                timeout = self.settings['interval'] if self.settings['auto_refresh'] and not self.demo else None
            if timeout is not None:
                # Start-to-start cadence: do not add a full interval after every response.
                timeout = max(0, timeout - (time.monotonic() - started))
                if failed:
                    timeout = max(1, timeout)
            self.refresh.wait(timeout)
        if hasattr(_HTTP, 'session'):
            _HTTP.session.close()

    def drain(self):
        self.check_account_login()
        try:
            while True:
                generation, (success, message) = self.space_results.get_nowait()
                self.space_busy = False
                if generation == self.generation:
                    self.alert_status.configure(text=message, fg=ACCENT if success else '#edbc84')
        except queue.Empty:
            pass
        latest = None
        try:
            while True:
                generation, event, payload = self.events.get_nowait()
                if self.demo or generation != self.generation:
                    continue
                if event in ('snapshot', 'timed_snapshot'):
                    rows = payload[0] if event == 'timed_snapshot' else payload
                    self.check_status_alerts(rows)
                    self.check_matchmaking_action(rows)
                elif event == 'error':
                    self.alert_baseline = {}
                    self.space_trigger.reset()
                latest = (event, payload)
        except queue.Empty:
            pass
        if latest is not None:
            event, payload = latest
            self.refresh_button.configure(text='새로고침 ↻', state='normal')
            if event == 'timed_snapshot':
                rows, duration, received, cadence = payload
                gap = f' · 수신 간격 {cadence:.2f}초' if cadence is not None else ''
                self.receive_stats = f' · 조회 {duration * 1000:.0f}ms · 표시 대기 {(time.monotonic() - received) * 1000:.0f}ms{gap}'
                self.accept_snapshot(rows, check_alerts=False)
            elif event == 'snapshot':
                self.accept_snapshot(payload, check_alerts=False)
            else:
                self.connected = False
                message = payload if self.direct_account and isinstance(payload, str) else '연결 대기 · 라이엇 클라이언트를 실행하고 로그인해 주세요.'
                self.connection_label.configure(text='●  ' + message, fg='#edbc84')
                self.render()
        self.timer = self.root.after(8, self.drain)

    def accept_snapshot(self, rows, check_alerts=True):
        if check_alerts:
            self.check_status_alerts(rows)
            self.check_matchmaking_action(rows)
        current = {}
        for row in rows:
            key = str(row.get('puuid') or row.get('name') or '')
            if key:
                current[key] = row
        for key, previous in self.rows.items():
            if key not in current:
                current[key] = {**previous, 'state': 'offline'}
        changed = current != self.rows or not self.connected
        self.rows = current
        self.connected = True
        self.last_success = datetime.now().strftime('%H:%M:%S')
        if self.demo:
            self.connection_label.configure(text=f'●  데모 모드 · {self.demo_step + 1}/{len(DEMO_SCENES)} · {DEMO_SCENES[self.demo_step][0]}', fg='#d5b5ff')
        else:
            if self.direct_account is not None:
                self.account_label.configure(text='별도 계정 · ' + self.direct_account.label)
                self.receive_stats = ' · 실시간 상태 수신'
            self.connection_label.configure(text=f'●  연결됨 · 마지막 확인 {self.last_success}{self.receive_stats}', fg=ACCENT)
        if changed:
            self.render()

    def render(self):
        selected = self.table.selection()
        yview = self.table.yview()
        display = []
        counts = {'PC 접속': 0, '게임 중': 0, '모바일': 0}
        pins = self.demo_pins if self.demo else self.pins
        query = self.search.get().strip().casefold()
        for key, row in self.rows.items():
            group, game, phase, detail, playing = describe(row)
            if group in counts:
                counts[group] += 1
            counts['게임 중'] += int(playing)
            name = app.get_display_name_from_presence(row)
            if self.filter != '전체' and self.filter != group:
                continue
            if key not in pins and self.filter == '전체' and ((group == '모바일' and not self.settings['show_mobile']) or
                                          (group == '오프라인' and not self.settings['show_offline'])):
                continue
            if query and query not in name.casefold():
                continue
            rank = 0 if playing else {'PC 접속': 1, '모바일': 2, '오프라인': 3}[group]
            if group == '모바일' and phase != '모바일 · 온라인':
                rank = 2.5
            if self.settings['sort_by'] == '이름순':
                rank = 0
            if key in pins:
                rank = pins.index(key) - len(pins)
                name = '★ ' + name
            if key in (self.demo_alert_friends if self.demo else self.alert_friends):
                name = '♪ ' + name
            display.append((rank, name.casefold(), key, (name, game, phase, detail), group, playing))
        for name, value in self.metrics.items():
            value.configure(text=str(counts[name]) if self.connected else '—')
        self.fit_columns(display)
        if self.connected and display and self.content_fit_pending:
            self.content_fit_pending = False
            self.fit_timer = self.root.after_idle(self.finish_content_fit)
        children = self.table.get_children()
        if children:
            self.table.delete(*children)
        # Hide cached rows while disconnected so stale game states look neither current nor offline.
        if self.connected:
            for _, _, key, values, group, playing in sorted(display):
                tag = 'playing' if playing else group
                if values[2] == '매칭 중':
                    tag = 'matchmaking'
                elif values[2] in ('요원 선택', '챔피언 선택'):
                    tag = 'selection'
                elif group == '모바일' and values[2] == '모바일 · 온라인':
                    tag = 'mobile_online'
                self.table.insert('', 'end', iid=key, values=values, tags=(tag,))
            if selected and self.table.exists(selected[0]):
                self.table.selection_set(selected[0])
            elif self.table.get_children():
                self.table.selection_set(self.table.get_children()[0])
            if yview:
                self.table.yview_moveto(yview[0])
        if not self.connected or not display:
            message = '연결을 기다리고 있습니다. 클라이언트 로그인 상태를 확인해 주세요.' if not self.connected else '조건에 맞는 친구가 없습니다.'
            self.empty.configure(text=message)
            self.empty.place(relx=.5, rely=.5, anchor='center')
        else:
            self.empty.place_forget()
        suffix = f'마지막 수신 {self.last_success} · ' if not self.connected and self.last_success else ''
        refresh_text = f"{self.settings['interval']}초마다 자동 갱신" if self.settings['auto_refresh'] else '자동 갱신 꺼짐 · 새로고침 버튼으로 갱신'
        note = '가상 친구로 검색·필터·상태 변화를 확인하세요. 실제 게임 연결 테스트는 아닙니다.' if self.demo else '오프라인 목록은 이번 실행에서 확인한 친구만 표시합니다.'
        if self.demo:
            suffix = ''
            refresh_text = '일시정지 · 이전/다음으로 이동' if self.demo_paused else f"{max(1, self.settings['interval'])}초 간격 재생"
        self.footer.configure(text=suffix + refresh_text + ' · ' + note)
        self.render_details()

    def render_details(self):
        selected = self.table.selection()
        selected_key = selected[0] if selected else None
        if self.marked_row != selected_key and self.marked_row and self.table.exists(self.marked_row):
            self.table.item(self.marked_row, image='')
        if selected_key:
            self.table.item(selected_key, image=self.selection_strip)
        self.marked_row = selected_key
        row = self.rows.get(selected[0]) if selected and self.connected else None
        watched = self.demo_alert_friends if self.demo else self.alert_friends
        self.alert_enabled.set(bool(selected and selected[0] in watched))
        self.alert_check.configure(state='normal' if row is not None else 'disabled')
        space_watched = self.demo_space_friends if self.demo else self.space_friends
        self.space_enabled.set(bool(selected and selected[0] in space_watched))
        self.space_check.configure(state='normal' if row is not None else 'disabled')
        pins = self.demo_pins if self.demo else self.pins
        pinned = bool(selected and selected[0] in pins)
        self.pin_button.configure(text='고정 해제' if pinned else '상단 고정',
                                  state='normal' if row is not None else 'disabled',
                                  fg=ACCENT if pinned else TEXT)
        cache_key = json.dumps(row, sort_keys=True, ensure_ascii=False) if row is not None else None
        if cache_key == self.detail_cache and row is not None:
            return
        self.detail_cache = cache_key
        texts = friend_details(row, describe(row)) if row is not None else ('친구를 선택하면 수신된 상세 정보가 표시됩니다.', '선택된 친구 없음')
        for widget, content in zip(self.detail_texts, texts):
            position = widget.yview()
            widget.configure(state='normal')
            widget.delete('1.0', 'end')
            widget.insert('1.0', content)
            widget.configure(state='disabled')
            if position:
                widget.yview_moveto(position[0])

    def remember_window_size(self, event):
        if event.widget is not self.root:
            return
        state = self.root.state()
        if state in ('normal', 'zoomed'):
            self.window_state = state
        if state == 'normal' and event.width > 100 and event.height > 100:
            self.normal_size = (event.width, event.height)

    def close(self):
        try:
            width, height = self.normal_size
            data = {'width': width, 'height': height, 'maximized': self.window_state == 'zoomed', 'layout_version': 3}
            temporary = self.window_path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
            temporary.replace(self.window_path)
        except OSError:
            pass
        self.stop.set()
        if self.direct_account is not None:
            self.direct_account.close()
        if self.login_cancel is not None:
            self.login_cancel.set()
        if self.login_child is not None and self.login_child.is_alive():
            self.login_child.join(timeout=1)
        if self.login_pipe is not None:
            self.login_pipe.close()
        self.refresh.set()
        self.root.after_cancel(self.timer)
        if self.fit_timer is not None:
            self.root.after_cancel(self.fit_timer)
        if self.demo_timer is not None:
            self.root.after_cancel(self.demo_timer)
        self.root.destroy()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    import argparse
    import ctypes
    parser = argparse.ArgumentParser(description='RiotWatcher desktop dashboard')
    parser.add_argument('--demo', action='store_true', help='Open the demo overview')
    arguments = parser.parse_args()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('RiotWatcher.Desktop')
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    dashboard = Dashboard(root)
    if arguments.demo:
        dashboard.toggle_demo()
    root.mainloop()
