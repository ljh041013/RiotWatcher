"""Activity-change notifications; scores and receipt timestamps are ignored."""
from pathlib import Path
import winsound
import app


def activity_signature(row):
    state = app._presence_state(row)
    if state in ('offline', 'unavailable'):
        return ('offline',)
    if app.is_mobile_presence(row):
        return ('mobile', 'away' if state in ('mobile', 'away') else state)
    status = app.presence_to_status(row)
    product = status.get('product') or 'riot_client'
    val = status.get('valorant') or {}
    league = status.get('league') or {}
    if product == 'valorant':
        phase = val.get('session_loop_state') or 'UNKNOWN'
        party = val.get('party_state')
        if phase not in ('INGAME', 'PREGAME') and party in ('MATCHMAKING', 'STARTING_MATCHMAKING'):
            phase = 'MATCHMAKING'
        return (product, phase, val.get('queue_id'), 'away' if state == 'away' else 'online')
    if product == 'league_of_legends':
        return (product, league.get('phase') or league.get('game_phase'), league.get('queue_id'), state)
    return (product, state)


def play_notification():
    winsound.PlaySound(str(Path(__file__).with_name('notification.wav')),
                       winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
