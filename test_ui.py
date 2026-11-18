import tkinter as tk
import unittest
import tempfile
import base64
import json
import time
from unittest.mock import patch
from pathlib import Path

from ui import Dashboard, describe, load_settings, DEFAULT_SETTINGS, demo_snapshot, DEMO_SCENES


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp.name) / 'settings.json'
        self.ui = Dashboard(self.root, start_worker=False, settings_path=self.settings_path)

    def tearDown(self):
        self.ui.close()
        self.temp.cleanup()

    def test_account_switch_clears_rows_and_ignores_old_stream(self):
        self.ui.accept_snapshot([{'puuid': 'old', 'name': '이전 친구', 'state': 'chat'}])
        old_generation = self.ui.generation
        self.ui.space_friends.add('old')
        with patch('ui.DirectAccount') as constructor:
            remote = constructor.return_value
            remote.label = 'B#KR1'
            self.ui.switch_account({'access_token': 'test-only', 'expires_at': 0})
            callback = constructor.call_args[0][1]
            self.assertEqual(self.ui.rows, {})
            self.assertEqual(self.ui.space_friends, set())
            self.ui.events.put((old_generation, 'snapshot', [{'puuid': 'old', 'state': 'chat'}]))
            callback('snapshot', [{'puuid': 'new', 'name': 'B의 친구', 'state': 'chat'}])
            self.root.after_cancel(self.ui.timer)
            self.ui.drain()
            self.assertEqual(set(self.ui.rows), {'new'})
            self.ui.switch_account(None)
            remote.close.assert_called_once()
            callback('snapshot', [{'puuid': 'new', 'state': 'chat'}])
            self.assertTrue(self.ui.events.empty())

    def test_mobile_filter_search_and_disconnect(self):
        self.ui.accept_snapshot([
            {'puuid': 'a', 'game_name': '친구A', 'game_tag': 'KR1', 'state': 'mobile', 'product': 'league_of_legends'},
            {'puuid': 'b', 'name': '친구B', 'state': 'dnd', 'product': 'league_of_legends', 'summary': 'in game'},
        ])
        self.assertEqual(str(self.ui.metrics['게임 중'].cget('text')), '1')
        self.assertEqual(str(self.ui.metrics['모바일'].cget('text')), '1')
        self.ui.set_filter('모바일')
        self.assertEqual(self.ui.table.get_children(), ('a',))
        self.ui.search.set('KR1')
        self.assertEqual(self.ui.table.get_children(), ('a',))
        self.ui.search.set('없는친구')
        self.assertEqual(self.ui.table.get_children(), ())
        self.ui.search.set('')
        self.ui.events.put((self.ui.generation, 'error', None))
        self.root.after_cancel(self.ui.timer)
        self.ui.drain()
        self.assertFalse(self.ui.connected)
        self.assertEqual(self.ui.table.get_children(), ())
        self.assertEqual(self.ui.metrics['게임 중'].cget('text'), '—')

    def test_offline_and_reconnection(self):
        friend = {'puuid': 'a', 'name': '친구', 'state': 'chat', 'product': 'riot_client'}
        self.ui.accept_snapshot([friend])
        self.ui.accept_snapshot([])
        self.ui.set_filter('오프라인')
        self.assertEqual(self.ui.table.item('a', 'values')[2], '오프라인')
        self.ui.accept_snapshot([friend])
        self.assertEqual(self.ui.table.get_children(), ())
        self.ui.set_filter('PC 접속')
        self.assertEqual(self.ui.table.get_children(), ('a',))

    def test_unknown_game_phase_is_not_playing(self):
        fields = describe({'product': 'league_of_legends', 'state': 'dnd'})
        self.assertEqual(fields[2], '클라이언트 접속')
        self.assertFalse(fields[4])

    def test_mobile_app_online_and_away_share_mobile_filter(self):
        self.ui.accept_snapshot([
            {'puuid': 'mobile1', 'name': '앱접속', 'product': 'ritoplus', 'state': 'chat'},
            {'puuid': 'mobile2', 'name': '자리비움', 'product': 'ritoplus', 'state': 'away'},
        ])
        self.ui.set_filter('모바일')
        self.assertEqual(len(self.ui.table.get_children()), 2)
        self.assertEqual(self.ui.table.item('mobile1', 'values')[2], '모바일 · 온라인')
        self.assertEqual(self.ui.table.item('mobile2', 'values')[2], '모바일 · 자리 비움')
        self.assertEqual(str(self.ui.metrics['게임 중'].cget('text')), '0')
        self.assertEqual(str(self.ui.metrics['모바일'].cget('text')), '2')

    def test_pin_survives_status_changes_sorting_and_restart(self):
        self.ui.accept_snapshot([
            {'puuid': 'a', 'name': 'A', 'product': 'valorant', 'state': 'chat'},
            {'puuid': 'z', 'name': 'Z', 'product': 'ritoplus', 'state': 'away'},
        ])
        self.ui.table.selection_set('z')
        self.ui.toggle_pin()
        self.assertEqual(self.ui.table.get_children()[0], 'z')
        self.assertTrue(self.ui.table.item('z', 'values')[0].startswith('★ '))
        self.ui.apply_settings({**DEFAULT_SETTINGS, 'sort_by': '이름순', 'show_offline': False})
        self.ui.accept_snapshot([{'puuid': 'a', 'name': 'A', 'state': 'chat'}])
        self.assertEqual(self.ui.table.get_children()[0], 'z')
        self.assertEqual(self.ui.table.item('z', 'values')[2], '오프라인')
        second_root = tk.Tk()
        second_root.withdraw()
        second = Dashboard(second_root, start_worker=False, settings_path=self.settings_path)
        self.assertEqual(second.pins, ['z'])
        second.close()
        self.ui.table.selection_set('z')
        self.ui.toggle_pin()
        self.assertEqual(self.ui.pins, [])
        self.assertNotIn('z', self.ui.table.get_children())

    def test_demo_pins_do_not_change_saved_pins(self):
        self.ui.accept_snapshot([{'puuid': 'real', 'name': 'Real', 'state': 'chat'}])
        self.ui.table.selection_set('real')
        self.ui.toggle_pin()
        self.ui.toggle_demo()
        self.ui.table.selection_set('demo-3')
        self.ui.toggle_pin()
        self.assertEqual(self.ui.table.get_children()[0], 'demo-3')
        self.assertEqual(json.loads(self.ui.pins_path.read_text(encoding='utf-8')), ['real'])
        self.ui.toggle_demo()
        self.assertEqual(self.ui.pins, ['real'])

    def test_demo_cycles_and_restores_live_session_without_mixing(self):
        self.ui.accept_snapshot([{'puuid': 'real', 'name': '실제친구', 'state': 'chat'}])
        self.ui.search.set('실제')
        old_generation = self.ui.generation
        self.ui.toggle_demo()
        self.assertNotIn('real', self.ui.rows)
        self.assertEqual(len(self.ui.table.get_children()), 8)
        self.assertIn('데모 모드', self.ui.connection_label.cget('text'))
        self.assertIsNone(self.ui.demo_timer)
        self.ui.select_demo_scene(1)
        self.assertEqual(self.ui.table.item('demo-1', 'values')[2], '로비')
        self.ui.request_refresh()
        self.assertEqual(self.ui.table.item('demo-1', 'values')[2], '매칭 중')
        self.ui.request_refresh()
        self.assertEqual(self.ui.table.item('demo-1', 'values')[2], '챔피언 선택')
        self.ui.request_refresh()
        self.assertEqual(self.ui.table.item('demo-1', 'values')[2], '게임 중')
        self.ui.select_demo_scene(6)
        self.assertEqual(self.ui.table.item('demo-1', 'values')[2], '오프라인')
        self.ui.toggle_demo()
        self.assertEqual(set(self.ui.rows), {'real'})
        self.assertEqual(self.ui.search.get(), '실제')
        self.assertIsNone(self.ui.demo_timer)
        self.ui.events.put((old_generation, 'snapshot', [{'puuid': 'stale'}]))
        self.root.after_cancel(self.ui.timer)
        self.ui.drain()
        self.assertEqual(set(self.ui.rows), {'real'})
        self.assertFalse(self.ui.connected)

    def test_settings_persist_validate_and_control_demo(self):
        settings = {**DEFAULT_SETTINGS, 'interval': 10, 'auto_refresh': False,
                    'show_mobile': False, 'show_offline': False, 'sort_by': '이름순'}
        self.ui.apply_settings(settings)
        self.assertEqual(load_settings(self.settings_path), settings)
        self.ui.toggle_demo()
        self.assertIsNone(self.ui.demo_timer)
        self.assertNotIn('demo-3', self.ui.table.get_children())
        self.assertNotIn('demo-5', self.ui.table.get_children())
        self.ui.set_filter('모바일')
        self.assertEqual(self.ui.table.get_children(), ('demo-3',))
        for invalid in (0, 0.001, 301, 'abc', 'nan', 'inf'):
            with self.assertRaises(ValueError):
                self.ui.apply_settings({**settings, 'interval': invalid})
        self.assertEqual(load_settings(self.settings_path), settings)
        self.ui.apply_settings({**settings, 'auto_refresh': True})
        self.assertIsNone(self.ui.demo_timer)
        self.ui.toggle_demo_play()
        self.assertIsNotNone(self.ui.demo_timer)

    def test_demo_match_flow_keeps_modes_and_clears_match_details(self):
        for friend, mode in [('demo-2', '일반전'), ('demo-6', '스파이크 돌격'), ('demo-7', '신속플레이')]:
            for scene, expected in [(1, '로비'), (2, '매칭 중'), (3, '요원 선택'), (4, '게임 중'), (5, '로비')]:
                row = next(row for row in demo_snapshot(scene) if row['puuid'] == friend)
                fields = describe(row)
                self.assertEqual(fields[2], expected)
                self.assertIn(mode, fields[3])
                self.assertEqual(fields[4], scene == 4)
                if scene == 5:
                    self.assertNotIn('Ascent', fields[3])
                    self.assertNotIn('7-5', fields[3])

    def test_demo_empty_disconnect_and_manual_navigation_pause(self):
        self.ui.toggle_demo()
        self.ui.toggle_demo_play()
        self.assertIsNotNone(self.ui.demo_timer)
        self.ui.select_demo_scene(7)
        self.assertIsNone(self.ui.demo_timer)
        self.assertEqual(self.ui.table.get_children(), ())
        self.assertTrue(self.ui.connected)
        self.assertEqual(str(self.ui.metrics['게임 중'].cget('text')), '0')
        self.ui.select_demo_scene(8)
        self.assertFalse(self.ui.connected)
        self.assertEqual(self.ui.metrics['게임 중'].cget('text'), '—')
        self.ui.select_demo_scene(len(DEMO_SCENES))
        self.assertEqual(self.ui.demo_step, 0)
        self.assertTrue(self.ui.connected)
        self.assertEqual(self.ui.table.item('demo-2', 'values')[2], '매칭 중')
        self.assertEqual(self.ui.table.item('demo-6', 'values')[2], '요원 선택')
        self.assertEqual(self.ui.table.item('demo-7', 'values')[2], '게임 중')

    def test_corrupt_settings_fall_back_to_defaults(self):
        self.settings_path.write_text('{bad', encoding='utf-8')
        self.assertEqual(load_settings(self.settings_path), DEFAULT_SETTINGS)

    def test_fractional_interval_persists_and_demo_timer_accepts_it(self):
        self.ui.apply_settings({**DEFAULT_SETTINGS, 'interval': 0.05})
        self.assertEqual(load_settings(self.settings_path)['interval'], 0.05)
        self.ui.toggle_demo()
        self.ui.toggle_demo_play()
        self.assertIsNotNone(self.ui.demo_timer)

    def test_latest_response_wins_and_unchanged_rows_are_not_redrawn(self):
        row = {'puuid': 'latest', 'name': '친구', 'state': 'chat'}
        self.ui.events.put((self.ui.generation, 'snapshot', [{'puuid': 'old'}]))
        self.ui.events.put((self.ui.generation, 'timed_snapshot', ([row], 0.005, time.monotonic(), 0.05)))
        self.root.after_cancel(self.ui.timer)
        self.ui.drain()
        self.assertEqual(set(self.ui.rows), {'latest'})
        self.assertIn('수신 간격 0.05초', self.ui.connection_label.cget('text'))
        with patch.object(self.ui, 'render') as render:
            self.ui.accept_snapshot([row])
            render.assert_not_called()

    def test_valorant_modes_and_lobby_selection(self):
        def presence(data):
            return {'product': 'valorant', 'state': 'chat',
                    'private': base64.b64encode(json.dumps(data).encode()).decode()}
        for queue_id, label in [('unrated', '일반전'), ('spikerush', '스파이크 돌격'),
                                ('swiftplay', '신속플레이'), ('competitive', '경쟁전')]:
            for location in ('root', 'matchPresenceData', 'partyPresenceData'):
                data = {'sessionLoopState': 'INGAME'}
                data.update({'queueId': queue_id} if location == 'root' else {location: {'queueId': queue_id}})
                self.assertIn(label, describe(presence(data))[3])
        lobby = describe(presence({'sessionLoopState': 'MENUS', 'queueId': 'swiftplay'}))
        self.assertIn('선택 모드: 신속플레이', lobby[3])
        self.assertFalse(lobby[4])
        self.assertIn('모드 정보 없음', describe(presence({'sessionLoopState': 'INGAME'}))[3])
        self.assertIn('알 수 없는 모드 (future)', describe(presence({'queueId': 'future'}))[3])


if __name__ == '__main__':
    unittest.main()
