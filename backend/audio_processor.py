import numpy as np
import librosa
import soundfile as sf
from typing import Callable, Optional, Tuple


class AudioProcessor:
    TARGET_SR = 22050

    def analyze_song(self, path: str) -> dict:
        y, sr = librosa.load(path, sr=self.TARGET_SR, mono=False)
        y_mono = librosa.to_mono(y) if y.ndim > 1 else y

        tempo, _ = librosa.beat.beat_track(y=y_mono, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])

        duration = librosa.get_duration(y=y_mono, sr=sr)

        chroma = librosa.feature.chroma_cqt(y=y_mono, sr=sr)
        key_idx = int(np.argmax(np.mean(chroma, axis=1)))
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

        return {
            "bpm": round(bpm, 1),
            "duration": round(duration, 1),
            "key": keys[key_idx],
            "sample_rate": sr,
        }

    def separate_stems(self, audio: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract vocals and instrumental via mid/side decomposition.
        Vocals live in the center (mid) channel; instruments in the sides.
        Works on stereo; falls back to returning the same signal for mono.
        """
        if audio.ndim == 1 or (audio.ndim == 2 and audio.shape[0] == 1):
            mono = audio.flatten()
            return mono, mono

        left, right = audio[0], audio[1]

        # Mid = center content (vocals, kick, bass)
        mid = (left + right) / 2.0
        # Side = stereo spread (instruments, pads, effects)
        side = (left - right) / 2.0

        def norm(x):
            peak = np.max(np.abs(x))
            return x / peak if peak > 1e-8 else x

        return norm(mid), norm(side)

    def time_stretch_to_bpm(
        self, audio: np.ndarray, current_bpm: float, target_bpm: float
    ) -> np.ndarray:
        if abs(current_bpm - target_bpm) < 0.5:
            return audio
        rate = target_bpm / current_bpm
        return librosa.effects.time_stretch(audio, rate=rate)

    def apply_pitch_shift(
        self, audio: np.ndarray, semitones: float
    ) -> np.ndarray:
        if abs(semitones) < 0.05:
            return audio
        return librosa.effects.pitch_shift(
            audio, sr=self.TARGET_SR, n_steps=semitones
        )

    def create_mix(
        self,
        song_a_path: str,
        song_b_path: str,
        vocals_from: str,          # "a" or "b"
        target_bpm: float,
        vocals_volume: float,
        instrumental_volume: float,
        pitch_shift: float,
        output_path: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> None:

        def step(p):
            if progress_callback:
                progress_callback(p)

        step(5)
        audio_a, _ = librosa.load(song_a_path, sr=self.TARGET_SR, mono=False)
        step(15)
        audio_b, _ = librosa.load(song_b_path, sr=self.TARGET_SR, mono=False)
        step(25)

        mono_a = librosa.to_mono(audio_a) if audio_a.ndim > 1 else audio_a
        mono_b = librosa.to_mono(audio_b) if audio_b.ndim > 1 else audio_b

        bpm_a = float(np.atleast_1d(
            librosa.beat.beat_track(y=mono_a, sr=self.TARGET_SR)[0]
        )[0])
        bpm_b = float(np.atleast_1d(
            librosa.beat.beat_track(y=mono_b, sr=self.TARGET_SR)[0]
        )[0])
        step(35)

        vocals_a, instr_a = self.separate_stems(audio_a)
        vocals_b, instr_b = self.separate_stems(audio_b)
        step(45)

        if vocals_from == "a":
            vocals, v_bpm = vocals_a, bpm_a
            instr, i_bpm = instr_b, bpm_b
        else:
            vocals, v_bpm = vocals_b, bpm_b
            instr, i_bpm = instr_a, bpm_a

        step(50)

        vocals = self.time_stretch_to_bpm(vocals, v_bpm, target_bpm)
        step(65)
        instr = self.time_stretch_to_bpm(instr, i_bpm, target_bpm)
        step(80)

        if abs(pitch_shift) > 0.05:
            vocals = self.apply_pitch_shift(vocals, pitch_shift)
            instr = self.apply_pitch_shift(instr, pitch_shift)
        step(88)

        length = min(len(vocals), len(instr))
        mixed = vocals[:length] * vocals_volume + instr[:length] * instrumental_volume

        peak = np.max(np.abs(mixed))
        if peak > 1e-8:
            mixed = mixed * (0.9 / peak)
        step(95)

        sf.write(output_path, mixed, self.TARGET_SR)
        step(100)
