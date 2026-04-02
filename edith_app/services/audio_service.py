from __future__ import annotations

import base64
import subprocess
import threading
import time

try:
    from comtypes import CLSCTX_ALL
except ImportError:
    CLSCTX_ALL = None

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from ctypes import POINTER, cast
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except ImportError:
    POINTER = None
    cast = None
    AudioUtilities = None
    IAudioEndpointVolume = None


class AudioService:
    def __init__(self) -> None:
        self._speech_process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._speaking = False
        self._fallback_volume = 50
        self._fallback_muted = False

    @property
    def tts_enabled(self) -> bool:
        return True

    @property
    def system_audio_enabled(self) -> bool:
        return AudioUtilities is not None and IAudioEndpointVolume is not None and CLSCTX_ALL is not None

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            if self._speech_process is not None and self._speech_process.poll() is not None:
                self._speech_process = None
                self._speaking = False
            return self._speaking

    def speak(self, text: str) -> None:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        self.stop()
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Rate = 1;"
            "$s.Volume = 100;"
            f"$s.Speak('{self._escape_ps(cleaned)}');"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        try:
            process = subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    encoded,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return
        with self._lock:
            self._speech_process = process
            self._speaking = True
        threading.Thread(target=self._watch_speech_process, args=(process,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            process = self._speech_process
            self._speech_process = None
            self._speaking = False
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=1)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def adjust_volume(self, delta: float) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            current = endpoint.GetMasterVolumeLevelScalar()
            new_volume = max(0.0, min(1.0, current + delta))
            endpoint.SetMasterVolumeLevelScalar(new_volume, None)
            return f"Volume is now {int(new_volume * 100)}%."
        if pyautogui is not None:
            presses = max(1, int(abs(delta) * 50))
            key = "volumeup" if delta > 0 else "volumedown"
            try:
                actual_before = self._read_system_volume_percent()
                if actual_before is not None:
                    self._fallback_volume = actual_before
                    self._fallback_muted = actual_before == 0
                for _ in range(presses):
                    pyautogui.press(key)
                self._fallback_muted = False
                direction = 2 * presses if delta > 0 else -2 * presses
                self._fallback_volume = max(0, min(100, self._fallback_volume + direction))
                actual = self._read_system_volume_percent(expected=self._fallback_volume)
                if actual is not None:
                    self._fallback_volume = actual
                    return f"Volume is now {actual}%."
                return "Adjusted system volume."
            except Exception:
                pass
        return "System volume controls are unavailable on this machine."

    def set_volume(self, level: int) -> str:
        endpoint = self._get_endpoint_volume()
        bounded = max(0, min(100, level))
        if endpoint is not None:
            endpoint.SetMasterVolumeLevelScalar(bounded / 100.0, None)
            return f"Volume set to {bounded}%."
        if pyautogui is not None:
            try:
                actual_before = self._read_system_volume_percent()
                if actual_before is not None:
                    current = actual_before
                    self._fallback_volume = actual_before
                    self._fallback_muted = actual_before == 0
                else:
                    current = 0 if self._fallback_muted else self._fallback_volume
                presses = max(0, min(50, abs(bounded - current) // 2))
                key = "volumeup" if bounded >= current else "volumedown"
                for _ in range(presses):
                    pyautogui.press(key)
                self._fallback_volume = bounded
                self._fallback_muted = bounded == 0
                actual = self._read_system_volume_percent(expected=bounded)
                if actual is not None:
                    self._fallback_volume = actual
                    self._fallback_muted = actual == 0
                    return f"Volume set to {actual}%."
                return f"Volume set close to {bounded}%."
            except Exception:
                pass
        return "System volume controls are unavailable on this machine."

    def mute(self) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            endpoint.SetMute(1, None)
            return "Volume muted."
        if pyautogui is not None:
            try:
                pyautogui.press("volumemute")
                self._fallback_muted = True
                return "Volume muted."
            except Exception:
                pass
        return "System volume controls are unavailable on this machine."

    def unmute(self) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            endpoint.SetMute(0, None)
            return "Volume unmuted."
        if pyautogui is not None:
            try:
                pyautogui.press("volumemute")
                self._fallback_muted = False
                return "Volume unmuted."
            except Exception:
                pass
        return "System volume controls are unavailable on this machine."

    def _watch_speech_process(self, process: subprocess.Popen) -> None:
        try:
            process.wait()
        except Exception:
            pass
        with self._lock:
            if self._speech_process is process:
                self._speech_process = None
                self._speaking = False

    def _get_endpoint_volume(self):
        if not self.system_audio_enabled or POINTER is None or cast is None:
            return None
        try:
            device = AudioUtilities.GetSpeakers()
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(interface, POINTER(IAudioEndpointVolume))
        except Exception:
            return None

    def _read_system_volume_percent(self, expected: int | None = None) -> int | None:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            try:
                return int(endpoint.GetMasterVolumeLevelScalar() * 100)
            except Exception:
                pass

        script = r"""
$code = @"
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f();
  int g();
  int h();
  int i();
  int j();
  int SetMasterVolumeLevelScalar(float level, System.Guid eventContext);
  int GetMasterVolumeLevelScalar(out float level);
}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
  int NotImpl1();
  int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
  int Activate(ref Guid id, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object interfacePointer);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject {}
public class VolumeReader {
  public static int GetVolume() {
    var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
    IMMDevice device;
    Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 1, out device));
    object endpointObj;
    var iid = typeof(IAudioEndpointVolume).GUID;
    Marshal.ThrowExceptionForHR(device.Activate(ref iid, 23, IntPtr.Zero, out endpointObj));
    float level;
    Marshal.ThrowExceptionForHR(((IAudioEndpointVolume)endpointObj).GetMasterVolumeLevelScalar(out level));
    return (int)Math.Round(level * 100);
  }
}
"@;
Add-Type -TypeDefinition $code -Language CSharp;
[VolumeReader]::GetVolume()
"""
        for attempt in range(2):
            if attempt:
                time.sleep(0.18)
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        script,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    shell=False,
                )
                output = (result.stdout or "").strip()
                if result.returncode == 0 and output.isdigit():
                    actual = max(0, min(100, int(output)))
                    if expected is not None and expected > 0 and actual == 0:
                        continue
                    return actual
            except Exception:
                pass
        return None

    def _escape_ps(self, text: str) -> str:
        return text.replace("'", "''")
