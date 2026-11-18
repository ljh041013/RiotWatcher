import time
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from unittest.mock import Mock

from riot_login import parse_redirect
from riot_account import XMLStream, Friends, DirectAccount, tag


class SeparateAccountTests(unittest.TestCase):
    def test_redirect_requires_exact_destination_and_state(self):
        fragment = urlencode({'state': 'expected', 'access_token': 'test-only',
                              'token_type': 'Bearer', 'expires_in': '3600'})
        url = 'https://playvalorant.com/opt_in#' + fragment
        self.assertEqual(parse_redirect(url, 'expected')['access_token'], 'test-only')
        with self.assertRaises(ValueError):
            parse_redirect(url, 'wrong')
        self.assertIsNone(parse_redirect(url.replace('playvalorant.com', 'playvalorant.com.attacker.test'), 'expected'))
        self.assertIsNone(parse_redirect(url.replace('https:', 'http:'), 'expected'))

    def test_callback_without_token_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_redirect('https://playvalorant.com/opt_in#state=expected', 'expected')

    def test_xml_handles_every_byte_boundary_including_utf8(self):
        stream = XMLStream()
        data = '<stream:stream xmlns:stream="http://etherx.jabber.org/streams"><presence><status>친구</status></presence><iq id="2"/>'.encode()
        stanzas = []
        for byte in data:
            stanzas.extend(stream.feed(bytes([byte])))
        self.assertEqual([tag(e) for e in stanzas], ['presence', 'iq'])
        self.assertEqual(stanzas[0][0].text, '친구')
        self.assertEqual(len(stream.root), 0)

    def test_xml_rejects_split_declarations(self):
        stream = XMLStream()
        stream.feed(b'<')
        with self.assertRaises(ValueError):
            stream.feed(b'!DOCTYPE stream [<!ENTITY x "bad">]>')

    def test_presence_resource_removal_preserves_mobile_and_names(self):
        friends = Friends()
        friends.apply(ET.fromstring('<iq><query xmlns="jabber:iq:riotgames:roster"><item jid="friend@kr1.pvp.net" name="Old"><id name="친구" tagline="KR1"/></item></query></iq>'))
        def presence(resource, product, state):
            return ET.fromstring(f'<presence from="friend@kr1.pvp.net/{resource}"><games><{product}><st>{state}</st></{product}></games></presence>')
        friends.apply(presence('desktop', 'valorant', 'chat'))
        friends.apply(presence('mobile', 'ritoplus', 'mobile'))
        self.assertEqual(friends.snapshot()[0]['product'], 'valorant')
        friends.apply(ET.fromstring('<presence from="friend@kr1.pvp.net/desktop" type="unavailable"/>'))
        row = friends.snapshot()[0]
        self.assertEqual((row['name'], row['product'], row['state']), ('친구#KR1', 'ritoplus', 'mobile'))
        friends.apply(presence('mobile', 'ritoplus', 'chat'))
        self.assertEqual(friends.snapshot()[0]['state'], 'chat')
        friends.apply(ET.fromstring('<presence from="friend@kr1.pvp.net/mobile" type="unavailable"/>'))
        self.assertEqual(friends.snapshot()[0]['state'], 'offline')

    def test_keystone_does_not_invent_desktop_presence(self):
        friends = Friends()
        friends.names['friend'] = '친구'
        friends.apply(ET.fromstring('<presence from="friend@kr1.pvp.net/mobile"><games><keystone><st>chat</st></keystone></games></presence>'))
        self.assertEqual(friends.snapshot()[0]['state'], 'offline')

    def test_handshake_preserves_following_stanzas(self):
        account = DirectAccount({}, Mock())
        account.socket = Mock()
        account.socket.recv.return_value = b'<stream:stream xmlns:stream="http://etherx.jabber.org/streams"><iq id="roster"/><presence from="friend"/>'
        stream = XMLStream()
        account.receive(stream, lambda e: e.get('id') == 'roster', time.monotonic() + 1)
        self.assertEqual(tag(stream.pending.popleft()), 'presence')

    def test_expired_credentials_are_cleared_without_connecting(self):
        credentials = {'access_token': 'test-only', 'expires_at': 0}
        callback = Mock()
        account = DirectAccount(credentials, callback)
        account.connect = Mock()
        account.run()
        account.connect.assert_not_called()
        self.assertEqual(credentials, {})
        self.assertEqual(callback.call_args[0][0], 'error')


if __name__ == '__main__':
    unittest.main()
