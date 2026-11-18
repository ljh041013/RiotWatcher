import base64
import json
import unittest
from matchmaking_trigger import MatchmakingTrigger


def row(phase='MENUS', party='DEFAULT', mode='swiftplay'):
    private = {'sessionLoopState': phase, 'partyState': party, 'queueId': mode}
    return {'puuid': 'friend', 'name': 'Friend', 'product': 'valorant', 'state': 'chat',
            'private': base64.b64encode(json.dumps(private).encode()).decode()}


class MatchmakingTests(unittest.TestCase):
    def test_one_trigger_per_entry_not_per_poll_or_mode_change(self):
        trigger = MatchmakingTrigger()
        watched = {'friend'}
        self.assertEqual(trigger.update([row()], watched), [])
        self.assertEqual(trigger.update([row(party='STARTING_MATCHMAKING')], watched), ['Friend'])
        for _ in range(20):
            self.assertEqual(trigger.update([row(party='MATCHMAKING')], watched), [])
        self.assertEqual(trigger.update([row(party='MATCHMAKING', mode='unrated')], watched), [])
        self.assertEqual(trigger.update([row('PREGAME')], watched), [])
        self.assertEqual(trigger.update([row()], watched), [])
        self.assertEqual(trigger.update([row(party='MATCHMAKING')], watched), ['Friend'])

    def test_initial_matching_and_reconnection_do_not_trigger(self):
        trigger = MatchmakingTrigger()
        matching = row(party='MATCHMAKING')
        self.assertEqual(trigger.update([matching], {'friend'}), [])
        trigger.reset()
        self.assertEqual(trigger.update([matching], {'friend'}), [])
        trigger.prime('friend', matching)
        self.assertEqual(trigger.update([matching], {'friend'}), [])

    def test_unwatched_and_mobile_do_not_trigger(self):
        trigger = MatchmakingTrigger()
        self.assertEqual(trigger.update([row()], set()), [])
        self.assertEqual(trigger.update([row(party='MATCHMAKING')], set()), [])
        trigger.update([{'puuid': 'friend', 'product': 'ritoplus', 'state': 'away'}], {'friend'})
        self.assertEqual(trigger.update([{'puuid': 'friend', 'product': 'ritoplus', 'state': 'chat'}], {'friend'}), [])


if __name__ == '__main__':
    unittest.main()
