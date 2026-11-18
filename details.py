"""Offline labels and inspection of fields actually supplied by the client."""
import json
from pathlib import Path
import app

try:
    METADATA = json.loads(Path(__file__).with_name('game_metadata.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    METADATA = {'maps': {}, 'tiers': {}}


def map_label(value):
    if not value:
        return '정보 없음'
    text = str(value)
    return METADATA['maps'].get(text.lower(), text.rsplit('/', 1)[-1] or text)


def safe_payload(value):
    if isinstance(value, dict):
        return {key: ('[숨김]' if any(part in key.lower() for part in ('token', 'password', 'authorization', 'jwt'))
                      else safe_payload(app._decode_presence_private(item) or item) if key in ('private', 'basic') and isinstance(item, str)
                      else safe_payload(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_payload(item) for item in value]
    return value


def friend_details(row, display):
    group, game, phase, _, _ = display
    lines = [app.get_display_name_from_presence(row), '', f'접속  {group}', f'게임  {game}', f'상태  {phase}']
    private = app._decode_presence_private(row.get('private')) or {}
    status = app.presence_to_status(row)
    val = status.get('valorant') or {}
    party = private.get('partyPresenceData') or {}
    player = private.get('playerPresenceData') or {}
    premier = private.get('premierPresenceData') or {}

    def field(label, value):
        if value is None or value == '':
            value = '미제공'
        elif isinstance(value, bool):
            value = '예' if value else '아니요'
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f'{label}  {value}')

    if group in ('오프라인', '모바일'):
        lines.extend(['', '현재 게임 정보는 확인되지 않습니다.', '전체 데이터에는 마지막 수신 값이 포함될 수 있습니다.'])
    elif row.get('product') == 'valorant':
        lines.extend(['', '게임 / 파티'])
        field('모드', display[3].split(' · ')[0])
        field('맵', map_label(val.get('match_map')))
        field('파티장 경기 점수', val.get('round_score'))
        size, maximum = val.get('party_size'), val.get('max_party_size')
        field('파티 인원', f'{size} / {maximum}' if size is not None and maximum is not None else size)
        field('파티장', val.get('is_party_owner'))
        field('파티 공개 상태', {'OPEN': '공개', 'CLOSED': '비공개'}.get(party.get('partyAccessibility'), party.get('partyAccessibility')))
        field('파티 상태', party.get('partyState') or private.get('partyState'))
        field('대기열 진입 시각 (원본)', party.get('queueEntryTime'))
        field('커스텀 게임 이름', party.get('customGameName'))
        field('커스텀 팀', party.get('customGameTeam'))
        field('크로스플레이', party.get('isPlayerCrossPlayEnabled'))
        lines.extend(['', '플레이어'])
        tier = val.get('competitive_tier')
        field('경쟁전 티어', METADATA['tiers'].get(str(tier), tier))
        field('계정 레벨', val.get('account_level'))
        field('리더보드 순위', player.get('leaderboardPosition'))
        field('플랫폼', player.get('platformOverride'))
        field('자리 비움', private.get('isIdle'))
        if premier:
            lines.extend(['', '프리미어'])
            field('팀 이름', premier.get('rosterName'))
            field('팀 태그', premier.get('rosterTag'))
            field('디비전', premier.get('division'))
            field('점수', premier.get('score'))
    else:
        field('상태 설명', row.get('summary'))
        for key, value in (status.get('league') or {}).items():
            field(key, value)
    lines.extend(['', '기본 정보'])
    for label, key in [('지역', 'region'), ('플랫폼', 'platform'), ('클라이언트', 'patchline'), ('상태 갱신 시각 (원본)', 'time'), ('플레이어 ID', 'puuid')]:
        field(label, row.get(key))
    return '\n'.join(lines), json.dumps(safe_payload(row), ensure_ascii=False, indent=2)
