import gc
import numpy as np
import librosa
import soundfile as sf
from typing import Callable, Optional, Tuple

# Stay well under Render free-tier's 512 MB limit.
# Lower SR reduces array sizes by ~27% vs 22050.
TARGET_SR = 16000
# Cap each track at 4 minutes so memory stays predictable.
MAX_DURATION = 240


class AudioProcessor:
    TARGET_SR = TARGET_SR

    def analyze_song(self, path: str) -> dict:
        # Load as mono immediately — halves memory vs stereo load.
        y, sr = librosa.load(path, sr=TARGET_SR, mono=True, duration=MAX_DURATION)

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])

        duration = librosa.get_duration(y=y, sr=sr)

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        key_idx = int(np.argmax(np.mean(chroma, axis=1)))
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

        del y
        gc.collect()

        return {
            "bpm": round(bpm, 1),
            "duration": round(min(duration, MAX_DURATION), 1),
            "key": keys[key_idx],
            "sample_rate": sr,
        }

    def _load_and_process(self, path: str) -> Tuple[np.ndarray, np.ndarray, float]:
        """Load one track, detect BPM, separate stems. Returns (vocals, instr, bpm)."""
        audio, _ = librosa.load(path, sr=TARGET_SR, mono=False, duration=MAX_DURATION)

        mono = librosa.to_mono(audio) if audio.ndim > 1 else audio
        bpm = float(np.atleast_1d(
            librosa.beat.beat_track(y=mono, sr=TARGET_SR)[0]
        )[0])
        del mono

        vocals, instr = self._separate_stems(audio)
        del audio
        gc.collect()

        return vocals, instr, bpm

    def _separate_stems(self, audio: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Mid/side decomposition: mid = vocals (center), side = instruments."""
        if audio.ndim == 1 or (audio.ndim == 2 and audio.shape[0] == 1):
            mono = audio.flatten()
            return mono.copy(), mono.copy()

        left, right = audio[0], audio[1]
        mid  = (left + right) / 2.0
        side = (left - right) / 2.0

        def norm(x):
            peak = np.max(np.abs(x))
            return x / peak if peak > 1e-8 else x

        return norm(mid), norm(side)

    def _time_stretch(self, audio: np.ndarray, current_bpm: float, target_bpm: float) -> np.ndarray:
        if abs(current_bpm - target_bpm) < 0.5:
            return audio
        stretched = librosa.effects.time_stretch(audio, rate=target_bpm / current_bpm)
        del audio
        gc.collect()
        return stretched

    def _pitch_shift(self, audio: np.ndarray, semitones: float) -> np.ndarray:
        if abs(semitones) < 0.05:
            return audio
        shifted = librosa.effects.pitch_shift(audio, sr=TARGET_SR, n_steps=semitones)
        del audio
        gc.collect()
        return shifted

    def create_mix(
        self,
        song_a_path: str,
        song_b_path: str,
        vocals_from: str,
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

        # ── Song A: load, BPM detect, stem-separate, then free raw audio ──
        step(5)
        vocals_a, instr_a, bpm_a = self._load_and_process(song_a_path)
        step(25)

        # ── Song B: same, sequentially so both stereo files are never in RAM together ──
        vocals_b, instr_b, bpm_b = self._load_and_process(song_b_path)
        step(45)

        # Select which stems to use and drop the unused ones immediately
        if vocals_from == "a":
            vocals, v_bpm = vocals_a, bpm_a
            instr,  i_bpm = instr_b,  bpm_b
            del vocals_b, instr_a
        else:
            vocals, v_bpm = vocals_b, bpm_b
            instr,  i_bpm = instr_a,  bpm_a
            del vocals_a, instr_b
        gc.collect()
        step(50)

        vocals = self._time_stretch(vocals, v_bpm, target_bpm)
        step(65)
        instr  = self._time_stretch(instr,  i_bpm, target_bpm)
        step(80)

        if abs(pitch_shift) > 0.05:
            vocals = self._pitch_shift(vocals, pitch_shift)
            instr  = self._pitch_shift(instr,  pitch_shift)
        step(88)

        length = min(len(vocals), len(instr))
        mixed  = vocals[:length] * vocals_volume + instr[:length] * instrumental_volume
        del vocals, instr
        gc.collect()

        peak = np.max(np.abs(mixed))
        if peak > 1e-8:
            mixed *= 0.9 / peak
        step(95)

        sf.write(output_path, mixed, TARGET_SR)
        del mixed
        gc.collect()
        step(100)
