import unittest
from unittest.mock import Mock, patch
from keyboard_action import send_space_to_valorant


class KeyboardActionTests(unittest.TestCase):
    def make_api(self, foreground):
        user, kernel = Mock(), Mock()
        user.GetForegroundWindow.side_effect = foreground
        user.IsWindowVisible.return_value = True
        user.IsIconic.return_value = False
        def pid(hwnd, pointer):
            pointer._obj.value = hwnd
        user.GetWindowThreadProcessId.side_effect = pid
        kernel.OpenProcess.side_effect = lambda access, inherit, pid: pid
        def image(handle, flags, buffer, size):
            buffer.value = 'C:\\Games\\VALORANT-Win64-Shipping.exe' if handle == 20 else 'C:\\Other.exe'
            return True
        kernel.QueryFullProcessImageNameW.side_effect = image
        user.EnumWindows.side_effect = lambda callback, param: callback(20, 0)
        user.SendInput.return_value = 1
        return user, kernel

    def test_focus_game_then_one_down_and_up(self):
        user, kernel = self.make_api([10, 20, 20])
        with patch('keyboard_action.ctypes.WinDLL', side_effect=[user, kernel]), patch('keyboard_action.time.sleep'):
            success, _ = send_space_to_valorant()
        self.assertTrue(success)
        user.SetForegroundWindow.assert_called_once_with(20)
        self.assertEqual(user.SendInput.call_count, 2)
        flags = [call.args[1]._obj.ki.dwFlags for call in user.SendInput.call_args_list]
        self.assertEqual(flags, [8, 10])

    def test_never_types_into_other_foreground_app(self):
        user, kernel = self.make_api(lambda: 10)
        with patch('keyboard_action.ctypes.WinDLL', side_effect=[user, kernel]), patch('keyboard_action.time.sleep'):
            success, _ = send_space_to_valorant()
        self.assertFalse(success)
        user.SendInput.assert_not_called()

    def test_unchecked_during_focus_cancels_keypress(self):
        user, kernel = self.make_api([10, 20])
        enabled = Mock(side_effect=[True, False])
        with patch('keyboard_action.ctypes.WinDLL', side_effect=[user, kernel]), patch('keyboard_action.time.sleep'):
            success, _ = send_space_to_valorant(enabled)
        self.assertFalse(success)
        user.SendInput.assert_not_called()

    def test_key_up_is_sent_even_if_hold_is_interrupted(self):
        user, kernel = self.make_api([20, 20])
        with patch('keyboard_action.ctypes.WinDLL', side_effect=[user, kernel]), patch('keyboard_action.time.sleep', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                send_space_to_valorant()
        self.assertEqual(user.SendInput.call_count, 2)


if __name__ == '__main__':
    unittest.main()
