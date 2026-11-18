import base64
import json
import unittest

import app
from details import friend_details, map_label, safe_payload
from ui import demo_snapshot, describe


class DetailTests(unittest.TestCase):
    def test_internal_map_paths_use_korean_names(self):
        self.assertEqual(map_label('/Game/Maps/Infinity/Infinity'), '어비스')
        self.assertEqual(map_label('/Game/Maps/Ascent/Ascent'), '어센트')
        self.assertEqual(map_label('/Game/Maps/Unknown/Unknown'), 'Unknown')
        row = next(row for row in demo_snapshot(4) if row['puuid'] == 'demo-7')
        self.assertIn('어비스', describe(row)[3])
        self.assertNotIn('/Game/', describe(row)[3])

    def test_zero_and_false_values_are_preserved(self):
        data = {'sessionLoopState': 'INGAME', 'queueId': 'swiftplay',
                'partyOwnerMatchScoreAllyTeam': 0, 'partyOwnerMatchScoreEnemyTeam': 0,
                'partyPresenceData': {'isPartyOwner': False},
                'playerPresenceData': {'accountLevel': 0, 'competitiveTier': 0}}
        row = {'product': 'valorant', 'state': 'chat', 'name': 'Test',
               'private': base64.b64encode(json.dumps(data).encode()).decode()}
        status = app.presence_to_status(row)
        self.assertEqual(status['valorant']['round_score'], '0-0')
        summary, raw = friend_details(row, describe(row))
        self.assertIn('파티장  아니요', summary)
        self.assertIn('계정 레벨  0', summary)
        self.assertEqual(json.loads(raw)['private']['playerPresenceData']['accountLevel'], 0)

    def test_all_extra_fields_survive_but_tokens_are_redacted(self):
        row = {'name': 'Friend', 'extraField': {'somethingNew': 12}, 'privateJwt': 'secret',
               'private': base64.b64encode(json.dumps({'custom': 42, 'authToken': 'secret'}).encode()).decode()}
        result = safe_payload(row)
        self.assertEqual(result['extraField']['somethingNew'], 12)
        self.assertEqual(result['private']['custom'], 42)
        self.assertNotIn('secret', json.dumps(result))

    def test_offline_details_do_not_claim_stale_game_is_current(self):
        row = next(row for row in demo_snapshot(4) if row['puuid'] == 'demo-7')
        row['state'] = 'offline'
        summary, raw = friend_details(row, describe(row))
        self.assertNotIn('파티장 경기 점수', summary)
        self.assertIn('마지막 수신', summary)
        self.assertIn('matchPresenceData', raw)


if __name__ == '__main__':
    unittest.main()
