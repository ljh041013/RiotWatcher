"""Detect queue entry once, independently of polling frequency and sound alerts."""
from notifications import activity_signature
import app


def is_matchmaking(row):
    signature = activity_signature(row)
    return len(signature) > 1 and (
        signature[:2] == ('valorant', 'MATCHMAKING')
        or signature[:2] == ('league_of_legends', 'in_queue'))


class MatchmakingTrigger:
    def __init__(self):
        self.previous = {}

    def reset(self):
        self.previous.clear()

    def prime(self, key, row):
        self.previous[key] = is_matchmaking(row)

    def update(self, rows, watched):
        incoming = {str(row.get('puuid') or row.get('name') or ''): row for row in rows}
        updated, changed = {}, []
        for key in watched:
            row = incoming.get(key)
            matching = is_matchmaking(row) if row is not None else False
            if key in self.previous and not self.previous[key] and matching:
                changed.append(app.get_display_name_from_presence(row))
            updated[key] = matching
        self.previous = updated
        return changed
