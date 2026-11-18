import base64
import copy
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import wave

from ui import Dashboard, demo_snapshot


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.ui = Dashboard(self.root, start_worker=False, settings_path=Path(self.temp.name)/'settings.json')
        self.sound_patch = patch('ui.play_notification')
        self.sound = self.sound_patch.start()

    def tearDown(self):
        self.ui.close()
        self.sound_patch.stop()
        self.temp.cleanup()

    def row(self, scene):
        return copy.deepcopy(next(row for row in demo_snapshot(scene) if row['puuid'] == 'demo-2'))

    def test_watched_activity_transitions_sound_but_initial_snapshot_does_not(self):
        self.ui.alert_friends = {'demo-2'}
        self.ui.accept_snapshot([self.row(1)])
        self.sound.assert_not_called()
        for scene in (2, 3, 4, 5):
            before = self.sound.call_count
            self.ui.accept_snapshot([self.row(scene)])
            self.assertEqual(self.sound.call_count, before + 1)

    def test_mode_changes_sound_scores_and_timestamps_do_not(self):
        self.ui.alert_friends = {'demo-2'}
        row = self.row(4)
        self.ui.accept_snapshot([row])
        private = json.loads(base64.b64decode(row['private']))
        private['partyOwnerMatchScoreAllyTeam'] = 8
        row['private'] = base64.b64encode(json.dumps(private).encode()).decode()
        row['time'] = 123456
        self.ui.accept_snapshot([row])
        self.sound.assert_not_called()
        private['queueId'] = 'swiftplay'
        row['private'] = base64.b64encode(json.dumps(private).encode()).decode()
        self.ui.accept_snapshot([row])
        self.sound.assert_called_once()

    def test_intermediate_events_alert_even_when_table_coalesces(self):
        self.ui.alert_friends = {'demo-2'}
        self.ui.accept_snapshot([self.row(1)])
        for scene in (2, 3):
            self.ui.events.put((self.ui.generation, 'snapshot', [self.row(scene)]))
        self.root.after_cancel(self.ui.timer)
        self.ui.drain()
        self.assertEqual(self.sound.call_count, 2)
        self.assertEqual(self.ui.table.item('demo-2', 'values')[2], '요원 선택')

    def test_opt_in_persists_and_unwatched_friends_are_silent(self):
        self.ui.accept_snapshot([self.row(1)])
        self.ui.accept_snapshot([self.row(2)])
        self.sound.assert_not_called()
        self.ui.table.selection_set('demo-2')
        self.ui.alert_enabled.set(True)
        self.ui.toggle_friend_alert()
        self.assertEqual(json.loads(self.ui.alerts_path.read_text()), ['demo-2'])
        self.ui.accept_snapshot([self.row(3)])
        self.sound.assert_called_once()
        self.ui.alert_enabled.set(False)
        self.ui.toggle_friend_alert()
        self.ui.accept_snapshot([self.row(4)])
        self.sound.assert_called_once()

    def test_reconnection_is_silent_and_audio_is_valid(self):
        self.ui.alert_friends = {'demo-2'}
        self.ui.accept_snapshot([self.row(1)])
        self.ui.events.put((self.ui.generation, 'error', None))
        self.ui.events.put((self.ui.generation, 'snapshot', [self.row(4)]))
        self.root.after_cancel(self.ui.timer)
        self.ui.drain()
        self.sound.assert_not_called()
        with wave.open(str(Path(__file__).with_name('notification.wav')), 'rb') as audio:
            self.assertGreater(audio.getnframes(), 0)
            self.assertLess(audio.getnframes() / audio.getframerate(), 1)


if __name__ == '__main__':
    unittest.main()
