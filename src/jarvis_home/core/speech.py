import asyncio
import shutil
import tempfile
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PCM16Audio:
    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> PCM16Audio: ...


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: PCM16Audio) -> str: ...


class MacSayTTS(TTSProvider):
    """Local macOS speech synthesis normalized to streamed PCM16 mono."""

    def __init__(self, voice: str | None = None, sample_rate: int = 16000):
        self.voice = voice
        self.sample_rate = sample_rate

    async def synthesize(self, text: str) -> PCM16Audio:
        if not shutil.which("say"):
            raise RuntimeError("macOS say is unavailable")
        with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as directory:
            output = Path(directory) / "speech.wav"
            command = [
                "say",
                "--file-format=WAVE",
                f"--data-format=LEI16@{self.sample_rate}",
                "-o",
                str(output),
            ]
            if self.voice:
                command.extend(["-v", self.voice])
            command.append(text)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode:
                raise RuntimeError(
                    f"Local TTS failed: {stderr.decode(errors='replace')[:160]}"
                )
            with wave.open(str(output), "rb") as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                    raise RuntimeError("Local TTS returned an unsupported PCM format")
                rate = wav.getframerate()
                data = wav.readframes(wav.getnframes())
                if not data:
                    raise RuntimeError("Local TTS produced no audio frames")
        return PCM16Audio(data=data, sample_rate=rate)


class UnavailableSTT(STTProvider):
    async def transcribe(self, audio: PCM16Audio) -> str:
        raise RuntimeError("No local STT provider is configured")
