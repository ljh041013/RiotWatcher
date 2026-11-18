import unittest
from unittest.mock import Mock, patch

import app


class PresenceTests(unittest.TestCase):
    def test_ritoplus_states_are_mobile_and_never_gameplay(self):
        for state, expected in [('chat', 'Mobile (online)'), ('away', 'Mobile (away)'), ('offline', 'Offline')]:
            row = {'product': 'ritoplus', 'state': state, 'summary': 'in game'}
            status = app.presence_to_status(row)
            self.assertEqual(status['status'], expected)
            self.assertFalse(status['in_game'])

    def test_ritoplus_wins_over_legacy_mobile_but_not_desktop(self):
        legacy = {'puuid': 'a', 'product': 'league_of_legends', 'state': 'mobile'}
        mobile = {'puuid': 'a', 'product': 'ritoplus', 'state': 'away'}
        desktop = {'puuid': 'a', 'product': 'valorant', 'state': 'dnd'}
        for rows, expected in [([legacy, mobile], mobile), ([mobile, legacy], mobile),
                               ([mobile, desktop], desktop), ([desktop, mobile], desktop)]:
            response = Mock()
            response.json.return_value = {'presences': rows}
            with patch.object(app, 'HAS_REQUESTS', True), patch.object(app.requests, 'get', return_value=response):
                self.assertEqual(app.fetch_presences(1, 'test'), [expected])

    def test_mobile_does_not_claim_gameplay(self):
        status = app.presence_to_status({
            'product': 'league_of_legends', 'state': 'mobile',
            'summary': 'in game',
        })
        self.assertFalse(status['in_game'])
        self.assertEqual(status['status'], 'Mobile (away)')

    def test_offline_overrides_stale_game_data(self):
        for state in ('offline', 'unavailable'):
            with self.subTest(state=state):
                self.assertFalse(app.is_online({
                    'availability': state, 'gameStatus': 'inGame',
                    'lol': {'gameStatus': 'inGame'},
                }))
                self.assertEqual(app.presence_to_status({
                    'state': state, 'product': 'league_of_legends',
                })['status'], 'Offline')

    def test_filter_and_desktop_preference_in_both_orders(self):
        mobile = {'puuid': 'a', 'product': 'league_of_legends', 'state': 'mobile'}
        desktop = {'puuid': 'a', 'product': 'riot_client', 'state': 'chat'}
        offline = {'puuid': 'b', 'product': 'league_of_legends', 'state': 'offline'}
        for rows in ([mobile, desktop, offline], [offline, desktop, mobile]):
            response = Mock()
            response.json.return_value = {'presences': rows}
            with patch.object(app, 'HAS_REQUESTS', True), patch.object(app.requests, 'get', return_value=response):
                self.assertEqual(app.fetch_presences(1, 'test'), [desktop])

    def test_desktop_league_still_reports_game(self):
        status = app.presence_to_status({
            'state': 'dnd', 'product': 'league_of_legends', 'summary': 'in game',
        })
        self.assertEqual(status['status'], 'Playing League of Legends (in game)')


if __name__ == '__main__':
    unittest.main()
